"""Security and resource-boundary contracts for the CDR HTTPS transport."""

from __future__ import annotations

import gzip
import hashlib
import socket
import time

import pytest

from cdr_http_policy import (
    HttpPolicy,
    HttpPolicyError,
    WireResponse,
    canonical_https_url,
    decode_limited_body,
    pagination_next_url,
    request_https,
    resolve_public_https_url,
)


def resolver_for(*addresses: str):
    def resolve(_host, port, *_args):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


def response(status=200, *, headers=None, body=b"{}", peer_ip="8.8.8.8"):
    return WireResponse(
        status=status,
        headers=headers or {"content-type": "application/json"},
        body=body,
        wire_bytes=len(body),
        inflated_bytes=len(body),
        wire_sha256=hashlib.sha256(body).hexdigest(),
        peer_ip=peer_ip,
    )


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://holder.example/products", "https_required"),
        ("https://user:secret@holder.example/products", "credentials_forbidden"),
        ("https://holder.example:8443/products", "port_forbidden"),
        ("https://holder.example/products#fragment", "fragment_forbidden"),
        ("https://127.0.0.1/products", "ip_literal_forbidden"),
        ("https://holder.example//evil", "invalid_url"),
    ],
)
def test_url_policy_rejects_unsafe_authorities_and_targets(url, code):
    with pytest.raises(HttpPolicyError) as caught:
        canonical_https_url(url)
    assert caught.value.code == code


def test_unicode_request_targets_are_canonicalized_to_ascii():
    target = canonical_https_url("https://holder.example/produits/épargne?q=café")
    assert target.request_target == "/produits/%C3%A9pargne?q=caf%C3%A9"
    assert target.url.endswith("/produits/%C3%A9pargne?q=caf%C3%A9")


def test_canonical_expansion_and_invalid_request_headers_remain_bounded():
    with pytest.raises(HttpPolicyError) as caught:
        canonical_https_url("https://holder.example/" + "é" * 2000)
    assert caught.value.code == "invalid_url"

    with pytest.raises(HttpPolicyError) as caught:
        request_https(
            "https://holder.example/products",
            {"Bad Header": "value"},
            timeout=5,
            resolver=resolver_for("8.8.8.8"),
            exchange=lambda *_args: pytest.fail("invalid headers must block the exchange"),
        )
    assert caught.value.code == "invalid_header"


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fc00::1"],
)
def test_ssrf_policy_rejects_every_non_public_dns_answer(address):
    with pytest.raises(HttpPolicyError) as caught:
        resolve_public_https_url(
            "https://holder.example/products",
            resolver=resolver_for(address),
        )
    assert caught.value.code == "ssrf_address_forbidden"


def test_mixed_public_and_private_dns_answers_fail_closed():
    with pytest.raises(HttpPolicyError, match="non-public"):
        resolve_public_https_url(
            "https://holder.example/products",
            resolver=resolver_for("8.8.8.8", "127.0.0.1"),
        )


def test_exchange_receives_only_the_resolved_public_address_and_bounded_timeout():
    seen = {}

    def exchange(target, headers, timeout, policy):
        seen.update(target=target, headers=headers, timeout=timeout, policy=policy)
        return response()

    result = request_https(
        "https://holder.example/products?page=1",
        {"Accept": "application/json"},
        timeout=90,
        deadline=3,
        resolver=resolver_for("8.8.8.8"),
        exchange=exchange,
        clock=lambda: 0,
    )
    assert result.status == 200
    assert seen["target"].addresses == ("8.8.8.8",)
    assert seen["target"].request_target == "/products?page=1"
    assert seen["timeout"] == 3
    assert seen["headers"]["accept-encoding"] == "gzip"


def test_same_origin_redirect_is_followed_and_recorded():
    targets = []

    def exchange(target, _headers, _timeout, _policy):
        targets.append(target.url)
        if len(targets) == 1:
            return response(302, headers={"Location": "/products?page=2"}, body=b"")
        return response(body=b'{"data":{}}')

    result = request_https(
        "https://holder.example/products?page=1",
        {},
        timeout=5,
        resolver=resolver_for("8.8.8.8"),
        exchange=exchange,
    )
    assert targets == [
        "https://holder.example/products?page=1",
        "https://holder.example/products?page=2",
    ]
    assert result.url == targets[-1]
    assert len(result.redirects) == 1


def test_cross_origin_redirect_is_rejected_before_second_connection():
    calls = []

    def exchange(target, _headers, _timeout, _policy):
        calls.append(target.url)
        return response(302, headers={"location": "https://other.example/private"}, body=b"")

    with pytest.raises(HttpPolicyError) as caught:
        request_https(
            "https://holder.example/products",
            {},
            timeout=5,
            resolver=resolver_for("8.8.8.8"),
            exchange=exchange,
        )
    assert caught.value.code == "redirect_cross_origin"
    assert calls == ["https://holder.example/products"]


def test_dns_rebinding_to_private_address_is_rejected_on_redirect_hop():
    resolutions = iter((resolver_for("8.8.8.8"), resolver_for("127.0.0.1")))

    def changing_resolver(*args):
        return next(resolutions)(*args)

    calls = []

    def exchange(target, _headers, _timeout, _policy):
        calls.append(target.url)
        return response(302, headers={"location": "/next"}, body=b"")

    with pytest.raises(HttpPolicyError) as caught:
        request_https(
            "https://holder.example/products",
            {},
            timeout=5,
            resolver=changing_resolver,
            exchange=exchange,
        )
    assert caught.value.code == "ssrf_address_forbidden"
    assert calls == ["https://holder.example/products"]


def test_pagination_accepts_relative_same_origin_only():
    current = "https://holder.example/products?page=1"
    assert pagination_next_url(current, "?page=2") == "https://holder.example/products?page=2"
    with pytest.raises(HttpPolicyError, match="holder origin"):
        pagination_next_url(current, "https://other.example/products?page=2")
    with pytest.raises(HttpPolicyError) as caught:
        pagination_next_url(current, "http://holder.example/products?page=2")
    assert caught.value.code == "https_required"


def test_compressed_inflated_and_final_body_caps_are_independent():
    compressed = gzip.compress(b"x" * 20)
    with pytest.raises(HttpPolicyError) as caught:
        decode_limited_body(
            compressed,
            content_encoding="gzip",
            policy=HttpPolicy(max_compressed_bytes=4, max_inflated_bytes=100, max_body_bytes=100),
        )
    assert caught.value.code == "compressed_body_too_large"

    with pytest.raises(HttpPolicyError) as caught:
        decode_limited_body(
            compressed,
            content_encoding="gzip",
            policy=HttpPolicy(max_compressed_bytes=100, max_inflated_bytes=5, max_body_bytes=100),
        )
    assert caught.value.code == "inflated_body_too_large"

    with pytest.raises(HttpPolicyError) as caught:
        decode_limited_body(
            compressed,
            content_encoding="gzip",
            policy=HttpPolicy(max_compressed_bytes=100, max_inflated_bytes=100, max_body_bytes=5),
        )
    assert caught.value.code == "body_too_large"

    with pytest.raises(HttpPolicyError) as caught:
        decode_limited_body(
            b"123456",
            content_encoding="identity",
            policy=HttpPolicy(max_body_bytes=5),
        )
    assert caught.value.code == "body_too_large"


def test_unsupported_encoding_and_exhausted_deadline_fail_closed():
    with pytest.raises(HttpPolicyError) as caught:
        decode_limited_body(b"payload", content_encoding="br")
    assert caught.value.code == "unsupported_content_encoding"

    with pytest.raises(HttpPolicyError) as caught:
        request_https(
            "https://holder.example/products",
            {},
            timeout=5,
            deadline=0,
            resolver=resolver_for("8.8.8.8"),
            exchange=lambda *_args: pytest.fail("deadline must block the exchange"),
            clock=lambda: 1,
        )
    assert caught.value.code == "deadline_exceeded"


def test_dns_resolution_is_bounded_by_the_request_deadline():
    def stalled_resolver(*_args):
        time.sleep(0.5)
        return resolver_for("8.8.8.8")("holder.example", 443)

    started = time.monotonic()
    with pytest.raises(HttpPolicyError) as caught:
        request_https(
            "https://holder.example/products",
            {},
            timeout=5,
            deadline=time.monotonic() + 0.03,
            resolver=stalled_resolver,
            exchange=lambda *_args: pytest.fail("deadline must block the exchange"),
        )
    assert caught.value.code == "deadline_exceeded"
    assert time.monotonic() - started < 0.25
