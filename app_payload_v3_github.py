"""GitHub backend for dormant, append-only payload-v3 promotion."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from cdr_domain.serialize import canonical_json_bytes

from app_payload_v3_promotion import (
    CANONICAL_REPO,
    CANDIDATE_TAG_PREFIX,
    CONTROL_BRANCH,
    LOCK_BRANCH,
    LOCK_FILENAME,
    POINTER_FILENAME,
    DATES_INDEX_FILENAME,
    V3_DATES_INDEX_LIMIT_BYTES,
    V3_LOCK_LIMIT_BYTES,
    V3_POINTER_LIMIT_BYTES,
    ConcurrencyError,
    PromotionError,
    RemoteNotFound,
    _release_url,
    _strict_object,
    _utc_now,
)


_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_OWNER_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_PRODUCER_COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_PUBLIC_BYTES = 33_554_432  # largest v3 compressed capability descriptor limit
CANONICAL_CANDIDATE_WORKFLOW = ".github/workflows/app-payload-v3-candidate.yml"
CANONICAL_CANDIDATE_ARTIFACT = "payload-v3-candidate"


def validate_candidate_run_metadata(
    run: Mapping[str, Any],
    main_branch: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> str:
    """Return the trusted producer SHA or fail closed on forged run provenance."""

    repository = run.get("repository")
    head_repository = run.get("head_repository")
    if (
        not isinstance(repository, Mapping)
        or repository.get("full_name") != CANONICAL_REPO
        or not isinstance(head_repository, Mapping)
        or head_repository.get("full_name") != CANONICAL_REPO
    ):
        raise PromotionError("candidate run is not from the canonical repository")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise PromotionError("candidate run is not completed successfully")
    if run.get("path") != CANONICAL_CANDIDATE_WORKFLOW:
        raise PromotionError("candidate run workflow is not allowlisted")
    if run.get("event") != "workflow_dispatch":
        raise PromotionError("candidate run event is not allowlisted")
    if run.get("head_branch") != "main":
        raise PromotionError("candidate run did not execute on protected main")
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or not _PRODUCER_COMMIT.fullmatch(head_sha):
        raise PromotionError("candidate run head SHA is invalid")
    if main_branch.get("name") != "main" or main_branch.get("protected") is not True:
        raise PromotionError("canonical main is not reported as protected")
    merge_base = comparison.get("merge_base_commit")
    if (
        comparison.get("status") not in {"ahead", "identical"}
        or not isinstance(merge_base, Mapping)
        or merge_base.get("sha") != head_sha
    ):
        raise PromotionError("candidate run head is not retained in protected main")
    return head_sha


def _validate_lock(value: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "state",
        "owner_token",
        "target_commit",
        "recorded_at",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise ConcurrencyError("promotion lock document is malformed")
    if value.get("state") not in {"acquired", "released"}:
        raise ConcurrencyError("promotion lock state is invalid")
    if not _OWNER_TOKEN.fullmatch(str(value.get("owner_token") or "")):
        raise ConcurrencyError("promotion lock owner token is invalid")
    if not _PRODUCER_COMMIT.fullmatch(str(value.get("target_commit") or "")):
        raise ConcurrencyError("promotion lock target commit is invalid")
    recorded_at = value.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise ConcurrencyError("promotion lock timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ConcurrencyError("promotion lock timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ConcurrencyError("promotion lock timestamp requires a timezone")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    _ALLOWED = {"github.com", "raw.githubusercontent.com"}

    def redirect_request(self, request, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urllib.parse.urlparse(newurl)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not (
                host in self._ALLOWED
                or host.endswith(".githubusercontent.com")
            )
        ):
            raise PromotionError("public verification redirect left trusted GitHub HTTPS")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def public_fetch(url: str, max_bytes: int, timeout: float = 30.0) -> bytes:
    """Fetch exact public GitHub bytes with trusted redirects and a hard cap."""

    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "raw.githubusercontent.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or max_bytes < 0
        or max_bytes > MAX_PUBLIC_BYTES
    ):
        raise PromotionError("public verification URL or byte limit is invalid")
    request = urllib.request.Request(
        url,
        headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"},
        method="GET",
    )
    opener = urllib.request.build_opener(_SafeRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > max_bytes:
                raise PromotionError("public verification response exceeds its byte limit")
            payload = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RemoteNotFound("public release object was not found") from error
        raise PromotionError(f"public verification failed with HTTP {error.code}") from error
    except (OSError, ValueError) as error:
        raise PromotionError("public verification transport failed") from error
    if len(payload) > max_bytes:
        raise PromotionError("public verification response exceeds its byte limit")
    return payload


class GitHubPromotionBackend:
    """Create-once releases plus append-only, non-force Git control refs."""

    def __init__(
        self,
        repo: str = CANONICAL_REPO,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        fetcher: Callable[[str, int], bytes] = public_fetch,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if repo != CANONICAL_REPO:
            raise PromotionError("v3 promotion is locked to the canonical repository")
        self.repo = repo
        self._runner = runner
        self._fetcher = fetcher
        self._sleeper = sleeper

    def _run(
        self, args: Sequence[str], *, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self._runner(
            list(args),
            input=input_text,
            capture_output=True,
            text=True,
            shell=False,
            timeout=60,
            check=False,
        )

    def _api(
        self,
        method: str,
        endpoint: str,
        body: Mapping[str, Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> Any:
        args = ["gh", "api", "--method", method, endpoint]
        input_text = None
        if body is not None:
            args += ["--input", "-"]
            input_text = json.dumps(body, separators=(",", ":"), allow_nan=False)
        result = self._run(args, input_text=input_text)
        if result.returncode != 0:
            if allow_404 and "404" in (result.stderr or ""):
                return None
            raise PromotionError(
                f"GitHub API {method} {endpoint} failed: {(result.stderr or '').strip()}"
            )
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise PromotionError("GitHub API returned invalid JSON") from error

    def _ref_head(self, branch: str) -> str | None:
        encoded = urllib.parse.quote(branch, safe="")
        value = self._api(
            "GET",
            f"repos/{self.repo}/git/ref/heads/{encoded}",
            allow_404=True,
        )
        if value is None:
            return None
        try:
            sha = str(value["object"]["sha"])
        except (KeyError, TypeError) as error:
            raise PromotionError("GitHub ref response is malformed") from error
        if not _GIT_OBJECT_ID.fullmatch(sha):
            raise PromotionError("GitHub ref returned an invalid object ID")
        return sha

    @staticmethod
    def _object_id(value: Any, label: str) -> str:
        if not isinstance(value, Mapping):
            raise PromotionError(f"GitHub {label} response is malformed")
        sha = value.get("sha")
        if not isinstance(sha, str) or not _GIT_OBJECT_ID.fullmatch(sha):
            raise PromotionError(f"GitHub {label} returned an invalid object ID")
        return sha

    def _tag_target(self, tag: str) -> str:
        encoded = urllib.parse.quote(tag, safe="")
        value = self._api("GET", f"repos/{self.repo}/git/ref/tags/{encoded}")
        try:
            kind = str(value["object"]["type"])
            sha = str(value["object"]["sha"])
        except (KeyError, TypeError) as error:
            raise PromotionError("GitHub tag response is malformed") from error
        if kind != "commit" or not _GIT_OBJECT_ID.fullmatch(sha):
            raise PromotionError("immutable candidate tag must point directly to a commit")
        return sha

    def _prepare_commit(
        self,
        branch: str,
        parent: str | None,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        tree_entries = []
        for path, payload in sorted(files.items()):
            blob = self._api(
                "POST",
                f"repos/{self.repo}/git/blobs",
                {"content": base64.b64encode(payload).decode("ascii"), "encoding": "base64"},
            )
            tree_entries.append(
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": self._object_id(blob, "blob"),
                }
            )
        tree_body: dict[str, Any] = {"tree": tree_entries}
        parents: list[str] = []
        if parent is not None:
            commit = self._api("GET", f"repos/{self.repo}/git/commits/{parent}")
            if not isinstance(commit, Mapping) or not isinstance(
                commit.get("tree"), Mapping
            ):
                raise PromotionError("GitHub parent commit response is malformed")
            tree_body["base_tree"] = self._object_id(
                commit["tree"], "parent tree"
            )
            parents = [parent]
        tree = self._api("POST", f"repos/{self.repo}/git/trees", tree_body)
        tree_sha = self._object_id(tree, "tree")
        commit = self._api(
            "POST",
            f"repos/{self.repo}/git/commits",
            {"message": message, "tree": tree_sha, "parents": parents},
        )
        return self._object_id(commit, "commit")

    def _install_ref(
        self, branch: str, expected_head: str | None, prepared_head: str
    ) -> None:
        if self._ref_head(branch) != expected_head:
            raise ConcurrencyError(f"{branch} changed before append")
        try:
            if expected_head is None:
                self._api(
                    "POST",
                    f"repos/{self.repo}/git/refs",
                    {"ref": f"refs/heads/{branch}", "sha": prepared_head},
                )
            else:
                encoded = urllib.parse.quote(branch, safe="")
                self._api(
                    "PATCH",
                    f"repos/{self.repo}/git/refs/heads/{encoded}",
                    {"sha": prepared_head, "force": False},
                )
        except PromotionError as error:
            # A connection can fail after GitHub accepted the ref write. Resolve
            # that ambiguity before reporting failure, so an installed exact
            # prepared head is treated as success rather than retried blindly.
            observed = self._ref_head(branch)
            if observed == prepared_head:
                return
            if observed != expected_head:
                raise ConcurrencyError(
                    f"{branch} changed during an indeterminate append"
                ) from error
            raise
        if self._ref_head(branch) != prepared_head:
            raise ConcurrencyError(f"{branch} append was not installed exactly")

    def _append_commit(
        self,
        branch: str,
        expected_head: str | None,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        prepared = self._prepare_commit(branch, expected_head, files, message)
        self._install_ref(branch, expected_head, prepared)
        return prepared

    def _fetch_raw(self, commit: str, path: str) -> bytes | None:
        limits = {
            POINTER_FILENAME: V3_POINTER_LIMIT_BYTES,
            DATES_INDEX_FILENAME: V3_DATES_INDEX_LIMIT_BYTES,
            LOCK_FILENAME: V3_LOCK_LIMIT_BYTES,
        }
        try:
            limit = limits[path]
        except KeyError as error:
            raise PromotionError("unsupported control file path") from error
        quoted = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        url = f"https://raw.githubusercontent.com/{self.repo}/{commit}/{quoted}"
        try:
            return self.fetch_url(url, limit)
        except RemoteNotFound:
            return None

    def acquire_lock(self, owner_token: str, target_commit: str) -> str:
        if not _OWNER_TOKEN.fullmatch(owner_token) or not _PRODUCER_COMMIT.fullmatch(
            target_commit
        ):
            raise ConcurrencyError("promotion lock identity is invalid")
        head = self._ref_head(LOCK_BRANCH)
        if head is not None:
            current_bytes = self._fetch_raw(head, LOCK_FILENAME)
            if current_bytes is None:
                raise ConcurrencyError("promotion lock branch has no lock document")
            current = _strict_object(current_bytes, "promotion lock")
            _validate_lock(current)
            if current.get("state") != "released":
                raise ConcurrencyError("another repository-wide promotion lock is active")
        payload = canonical_json_bytes(
            {
                "schema_version": 1,
                "state": "acquired",
                "owner_token": owner_token,
                "target_commit": target_commit,
                "recorded_at": _utc_now(),
            }
        )
        return self._append_commit(
            LOCK_BRANCH,
            head,
            {LOCK_FILENAME: payload},
            f"acquire v3 promotion {owner_token}",
        )

    def release_lock(self, owner_token: str) -> str:
        head = self._ref_head(LOCK_BRANCH)
        if head is None:
            raise ConcurrencyError("promotion lock disappeared before release")
        current_bytes = self._fetch_raw(head, LOCK_FILENAME)
        if current_bytes is None:
            raise ConcurrencyError("promotion lock document disappeared before release")
        current = _strict_object(current_bytes, "promotion lock")
        _validate_lock(current)
        if current.get("state") != "acquired" or current.get("owner_token") != owner_token:
            raise ConcurrencyError("promotion lock owner token changed before release")
        payload = canonical_json_bytes(
            {**current, "state": "released", "recorded_at": _utc_now()}
        )
        return self._append_commit(
            LOCK_BRANCH,
            head,
            {LOCK_FILENAME: payload},
            f"release v3 promotion {owner_token}",
        )

    def _release(self, tag: str) -> Mapping[str, Any] | None:
        encoded = urllib.parse.quote(tag, safe="")
        value = self._api(
            "GET", f"repos/{self.repo}/releases/tags/{encoded}", allow_404=True
        )
        if value is not None and not isinstance(value, Mapping):
            raise PromotionError(f"release metadata is malformed for {tag}")
        return value

    def ensure_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        exact_metadata: bool,
    ) -> None:
        release = self._release(tag)
        if release is None:
            result = self._run(
                [
                    "gh",
                    "release",
                    "create",
                    tag,
                    "--repo",
                    self.repo,
                    "--target",
                    target_commit,
                    "--title",
                    title,
                    "--notes",
                    notes,
                    "--latest=false",
                ]
            )
            if result.returncode != 0:
                # A concurrent create may have won. Accept only the exact object
                # verified below; never update the existing release to recover.
                release = self._release(tag)
                if release is None:
                    raise PromotionError(
                        f"create-once release {tag} failed: "
                        f"{(result.stderr or '').strip()}"
                    )
            else:
                release = self._release(tag)
        if release is None:
            raise PromotionError(f"release {tag} is absent after create")
        if exact_metadata:
            if (
                release.get("tag_name") != tag
                or release.get("name") != title
                or (release.get("body") or "") != notes
                or release.get("draft") is not False
                or release.get("prerelease") is not False
            ):
                raise PromotionError(f"immutable release {tag} metadata differs")
            if self._tag_target(tag) != target_commit:
                raise PromotionError(f"immutable release {tag} targets another commit")

    def put_immutable_asset(self, tag: str, name: str, payload: bytes) -> None:
        if name in self.list_asset_names(tag):
            if self.fetch_url(_release_url(self.repo, tag, name), len(payload)) != payload:
                raise PromotionError(f"immutable release asset differs: {tag}/{name}")
            return
        with tempfile.TemporaryDirectory(prefix="ar-v3-upload-") as temporary:
            path = Path(temporary) / name
            path.write_bytes(payload)
            result = self._run(
                ["gh", "release", "upload", tag, str(path), "--repo", self.repo]
            )
        if result.returncode != 0:
            try:
                existing = self.fetch_url(_release_url(self.repo, tag, name), len(payload))
            except PromotionError as error:
                raise PromotionError(
                    f"immutable release upload failed: {(result.stderr or '').strip()}"
                ) from error
            if existing != payload:
                raise PromotionError("concurrent immutable release asset differs")
        published = self.fetch_url(_release_url(self.repo, tag, name), len(payload))
        if published != payload:
            raise PromotionError("public immutable release verification failed")

    def list_candidate_tags(self) -> Sequence[str]:
        result = self._run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repo}/releases?per_page=100",
            ]
        )
        if result.returncode != 0:
            raise PromotionError(
                f"complete candidate listing failed: {(result.stderr or '').strip()}"
            )
        try:
            pages = json.loads(result.stdout)
            if not isinstance(pages, list) or any(
                not isinstance(page, list) for page in pages
            ):
                raise TypeError("candidate pages are not arrays")
            releases = [release for page in pages for release in page]
            if any(not isinstance(release, Mapping) for release in releases):
                raise TypeError("candidate release is not an object")
        except (json.JSONDecodeError, TypeError) as error:
            raise PromotionError("complete candidate listing is malformed") from error
        tags = sorted(
            str(release.get("tag_name"))
            for release in releases
            if str(release.get("tag_name") or "").startswith(CANDIDATE_TAG_PREFIX)
        )
        if len(tags) != len(set(tags)):
            raise PromotionError("candidate listing contains duplicate tags")
        return tags

    def list_asset_names(self, tag: str) -> Sequence[str]:
        release = self._release(tag)
        if release is None or not isinstance(release.get("assets"), list):
            raise PromotionError(f"release asset listing failed for {tag}")
        assets = release["assets"]
        if any(not isinstance(asset, Mapping) for asset in assets):
            raise PromotionError(f"release asset listing is malformed for {tag}")
        names = [asset.get("name") for asset in assets]
        if (
            any(not isinstance(name, str) or not name for name in names)
            or len(names) != len(set(names))
        ):
            raise PromotionError(f"release asset listing is malformed for {tag}")
        return sorted(str(name) for name in names)

    def fetch_url(self, url: str, max_bytes: int) -> bytes:
        last_error: PromotionError | None = None
        for attempt in range(4):
            try:
                return self._fetcher(url, max_bytes)
            except PromotionError as error:
                last_error = error
                if attempt < 3:
                    self._sleeper(float(attempt + 1))
        raise last_error or PromotionError("public verification failed")

    def control_head(self) -> str | None:
        return self._ref_head(CONTROL_BRANCH)

    def verify_candidate_run(self, run_id: str) -> str:
        if not re.fullmatch(r"[1-9][0-9]*", run_id):
            raise PromotionError("candidate run ID must be a positive integer")
        run = self._api("GET", f"repos/{self.repo}/actions/runs/{run_id}")
        if not isinstance(run, Mapping):
            raise PromotionError("candidate run metadata is malformed")
        head_sha = run.get("head_sha")
        if not isinstance(head_sha, str) or not _PRODUCER_COMMIT.fullmatch(head_sha):
            raise PromotionError("candidate run head SHA is invalid")
        main_branch = self._api("GET", f"repos/{self.repo}/branches/main")
        comparison = self._api(
            "GET", f"repos/{self.repo}/compare/{head_sha}...main"
        )
        if not isinstance(main_branch, Mapping) or not isinstance(
            comparison, Mapping
        ):
            raise PromotionError("protected-main provenance metadata is malformed")
        return validate_candidate_run_metadata(run, main_branch, comparison)

    def fetch_control_file(self, commit: str, path: str) -> bytes | None:
        return self._fetch_raw(commit, path)

    def prepare_control_commit(
        self,
        parent: str | None,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        return self._prepare_commit(CONTROL_BRANCH, parent, files, message)

    def install_control_head(
        self, expected_head: str | None, prepared_head: str
    ) -> None:
        self._install_ref(CONTROL_BRANCH, expected_head, prepared_head)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only provenance checks for dormant payload-v3 promotion."
    )
    parser.add_argument("--verify-candidate-run", metavar="RUN_ID", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    print(GitHubPromotionBackend().verify_candidate_run(args.verify_candidate_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL_CANDIDATE_ARTIFACT",
    "CANONICAL_CANDIDATE_WORKFLOW",
    "GitHubPromotionBackend",
    "public_fetch",
    "validate_candidate_run_metadata",
]
