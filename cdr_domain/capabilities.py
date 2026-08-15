"""Deterministic builders for dormant v3 capability assets."""

from __future__ import annotations

import binascii
import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Iterable

from .contract_validation import validate_asset_descriptor, validate_contract
from .models import Availability, CanonicalProduct, ClassificationStatus
from .serialize import canonical_json_bytes, to_primitive
from .validate import validate_canonical_product


CORE_SCHEMA_ID = (
    "https://australianrates.app/contracts/v3/canonical-core-v3.schema.json"
)
CORE_COHORT = "confirmed-consumer-products"
CORE_RELEASE_PREFIX = (
    "https://github.com/yanniedog/AR-local/releases/download/app-payload-gen/"
)


@dataclass(frozen=True)
class CoreCapability:
    """Exact immutable bytes and metadata for one canonical core asset."""

    encoded_bytes: bytes
    decoded_bytes: bytes
    sha256: str

    @property
    def filename(self) -> str:
        return f"{self.sha256}.json.gz"

    def descriptor(self) -> dict[str, object]:
        return {
            "schema_id": CORE_SCHEMA_ID,
            "media_type": "application/json",
            "encoding": "gzip",
            "compressed_bytes": len(self.encoded_bytes),
            "uncompressed_bytes": len(self.decoded_bytes),
            "sha256": self.sha256,
            "url": CORE_RELEASE_PREFIX + self.filename,
            "cohort": CORE_COHORT,
            "capability": "core",
        }


def deterministic_gzip(payload: bytes) -> bytes:
    """Return gzip bytes with a fixed header, timestamp, and OS marker."""

    if not isinstance(payload, bytes):
        raise TypeError("gzip payload must be exact bytes")
    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=-zlib.MAX_WBITS,
    )
    body = compressor.compress(payload) + compressor.flush()
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack(
        "<II",
        binascii.crc32(payload) & 0xFFFFFFFF,
        len(payload) & 0xFFFFFFFF,
    )
    return header + body + trailer


def build_core_capability(
    products: Iterable[CanonicalProduct],
    *,
    observation_date: str,
    normalization_version: str,
) -> CoreCapability:
    """Build the lean core from confirmed, public products with visible rates."""

    ordered = tuple(sorted(products, key=lambda item: item.identity.product_uid))
    seen: set[str] = set()
    for product in ordered:
        validate_canonical_product(product)
        product_uid = product.identity.product_uid
        if product_uid in seen:
            raise ValueError("core candidate contains a duplicate product_uid")
        seen.add(product_uid)
        if (
            product.classification.classification_status
            is not ClassificationStatus.CONFIRMED
            or product.evidence.availability is not Availability.PUBLIC
            or not product.rates
        ):
            raise ValueError("core candidate contains an ineligible product")
        if product.normalization_version != normalization_version:
            raise ValueError(
                "core products must share the generation normalization version"
            )

    core = {
        "schema_version": 3,
        "normalization_version": normalization_version,
        "observation_date": observation_date,
        "products": [to_primitive(product) for product in ordered],
    }
    validate_contract("canonical-core-v3.schema.json", core)
    decoded = canonical_json_bytes(core)
    encoded = deterministic_gzip(decoded)
    capability = CoreCapability(
        encoded_bytes=encoded,
        decoded_bytes=decoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
    validate_asset_descriptor(capability.descriptor())
    return capability


__all__ = [
    "CORE_COHORT",
    "CORE_SCHEMA_ID",
    "CoreCapability",
    "build_core_capability",
    "deterministic_gzip",
]
