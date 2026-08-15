"""GitHub release staging and immutable candidate-census boundary for payload v3."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app_payload_v3_state import (
    CANDIDATE_TAG_PREFIX,
    CandidateReleaseRecord,
    PromotionError,
    release_url,
    validate_candidate_draft_assets,
    validate_candidate_release_identity,
)


_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PRODUCER_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class GitHubReleaseMixin:
    """Release operations mixed into the authenticated GitHub backend."""

    def _release(self, tag: str) -> Mapping[str, Any] | None:
        encoded = urllib.parse.quote(tag, safe="")
        value = self._api(
            "GET", f"repos/{self.repo}/releases/tags/{encoded}", allow_404=True
        )
        if value is not None and not isinstance(value, Mapping):
            raise PromotionError(f"release metadata is malformed for {tag}")
        return value

    def _release_write(self, args):
        try:
            return self._run(args)
        except (subprocess.TimeoutExpired, PromotionError):
            return None

    @staticmethod
    def _write_error(result) -> str:
        return "timed out with an unknown outcome" if result is None else (result.stderr or "").strip()

    def _validate_candidate_release(
        self, release: Mapping[str, Any], tag: str, title: str, notes: str, target: str
    ) -> None:
        direct_target = self._tag_target(tag, allow_missing=release.get("draft") is True)
        validate_candidate_release_identity(
            release, tag, title=title, notes=notes,
            target_commit=target, direct_tag_target=direct_target,
        )

    def _candidate_draft_missing(
        self,
        release: Mapping[str, Any],
        tag: str,
        title: str,
        notes: str,
        target_commit: str,
        assets: Mapping[str, bytes],
    ) -> Sequence[str] | None:
        self._validate_candidate_release(release, tag, title, notes, target_commit)
        if release.get("draft") is False:
            self._verify_published_candidate(
                release, tag, title, notes, target_commit, assets
            )
            return None
        return validate_candidate_draft_assets(release, assets)

    def publish_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        assets: Mapping[str, bytes],
        owner_token: str,
    ) -> None:
        if not assets or any(Path(name).name != name for name in assets):
            raise PromotionError("candidate release asset inventory is invalid")
        release = self._release(tag)
        if release is None:
            self.renew_lock(owner_token)
            result = self._release_write(
                [
                    "gh", "release", "create", tag, "--repo", self.repo,
                    "--target", target_commit, "--title", title, "--notes", notes,
                    "--draft", "--latest=false",
                ]
            )
            release = self._release(tag)
            if result is None or result.returncode != 0:
                self.renew_lock(owner_token)
            if release is None:
                raise PromotionError(
                    f"create-once candidate draft {tag} failed: "
                    f"{self._write_error(result)}"
                )
        if release is None:
            raise PromotionError(f"candidate draft {tag} is absent after create")
        missing = self._candidate_draft_missing(
            release, tag, title, notes, target_commit, assets
        )
        if missing is None:
            return

        for name in missing:
            payload = assets[name]
            self.renew_lock(owner_token)
            release = self._release(tag)
            if release is None:
                raise PromotionError(f"candidate draft {tag} disappeared before upload")
            current_missing = self._candidate_draft_missing(
                release, tag, title, notes, target_commit, assets
            )
            if current_missing is None:
                return
            if name not in current_missing:
                continue
            with tempfile.TemporaryDirectory(prefix="ar-v3-upload-") as temporary:
                path = Path(temporary) / name
                path.write_bytes(payload)
                result = self._release_write(
                    ["gh", "release", "upload", tag, str(path), "--repo", self.repo]
                )
            release = self._release(tag)
            if result is None or result.returncode != 0:
                self.renew_lock(owner_token)
            if release is None:
                raise PromotionError(
                    f"candidate draft upload failed: {self._write_error(result)}"
                )
            current_missing = self._candidate_draft_missing(
                release, tag, title, notes, target_commit, assets
            )
            if current_missing is None:
                return
            if name in current_missing:
                raise PromotionError(f"candidate draft asset verification failed: {tag}/{name}")
        self.renew_lock(owner_token)
        release = self._release(tag)
        if release is None:
            raise PromotionError(f"candidate draft {tag} disappeared before publish")
        current_missing = self._candidate_draft_missing(
            release, tag, title, notes, target_commit, assets
        )
        if current_missing is None:
            return
        if current_missing:
            raise PromotionError("candidate draft asset set is incomplete before publish")
        result = self._release_write(
            ["gh", "release", "edit", tag, "--repo", self.repo, "--draft=false"]
        )
        release = self._release(tag)
        if result is None or result.returncode != 0:
            self.renew_lock(owner_token)
        if release is None or release.get("draft") is not False:
            raise PromotionError(
                f"candidate draft publish failed: {self._write_error(result)}"
            )
        self._verify_published_candidate(release, tag, title, notes, target_commit, assets)

    def _verify_published_candidate(
        self,
        release: Mapping[str, Any],
        tag: str,
        title: str,
        notes: str,
        target_commit: str,
        assets: Mapping[str, bytes],
    ) -> None:
        self.verify_candidate_release(
            tag, title=title, notes=notes, target_commit=target_commit
        )
        if set(self.list_asset_names(tag)) != set(assets):
            raise PromotionError("published candidate release asset set differs")
        for name, payload in assets.items():
            self.verify_immutable_asset(tag, name, payload)

    def verify_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
    ) -> None:
        release = self._release(tag)
        if release is None or (
            release.get("tag_name") != tag
            or release.get("name") != title
            or (release.get("body") or "") != notes
            or release.get("draft") is not False
            or release.get("prerelease") is not False
        ):
            raise PromotionError(f"immutable release {tag} metadata differs")
        if self._tag_target(tag) != target_commit:
            raise PromotionError(f"immutable release {tag} targets another commit")

    def verify_immutable_asset(self, tag: str, name: str, payload: bytes) -> None:
        release = self._release(tag)
        if release is None or release.get("draft") is not False:
            raise PromotionError(f"immutable release is absent or unpublished: {tag}")
        if name not in self.list_asset_names(tag):
            raise PromotionError(f"immutable release asset is absent: {tag}/{name}")
        if self.fetch_url(release_url(self.repo, tag, name), len(payload)) != payload:
            raise PromotionError(f"immutable release asset differs: {tag}/{name}")

    def list_candidate_releases(self) -> Sequence[CandidateReleaseRecord]:
        release_result = self._run(
            ["gh", "api", "--paginate", "--slurp",
             f"repos/{self.repo}/releases?per_page=100"]
        )
        if release_result.returncode != 0:
            raise PromotionError(
                "complete candidate listing failed: "
                f"{(release_result.stderr or '').strip()}"
            )
        encoded_prefix = urllib.parse.quote(f"tags/{CANDIDATE_TAG_PREFIX}", safe="/")
        ref_result = self._run(
            ["gh", "api", "--paginate", "--slurp",
             f"repos/{self.repo}/git/matching-refs/{encoded_prefix}?per_page=100"]
        )
        if ref_result.returncode != 0:
            raise PromotionError(
                "complete candidate tag listing failed: "
                f"{(ref_result.stderr or '').strip()}"
            )
        releases, refs = self._candidate_pages(release_result.stdout, ref_result.stdout)
        targets: dict[str, str] = {}
        for ref in refs:
            full_ref = ref.get("ref")
            target = ref.get("object")
            if (
                not isinstance(full_ref, str)
                or not full_ref.startswith("refs/tags/")
                or not isinstance(target, Mapping)
                or target.get("type") != "commit"
                or not _GIT_OBJECT_ID.fullmatch(str(target.get("sha") or ""))
            ):
                raise PromotionError("candidate tag provenance is malformed")
            tag = full_ref[len("refs/tags/") :]
            if not tag.startswith(CANDIDATE_TAG_PREFIX) or tag in targets:
                raise PromotionError("candidate tag provenance is ambiguous")
            targets[tag] = str(target["sha"])
        records = self._candidate_records(releases, targets)
        tags = [record.tag for record in records]
        if len(tags) != len(set(tags)):
            raise PromotionError("candidate listing contains duplicate tags")
        if not set(targets).issubset(tags):
            raise PromotionError("candidate tag and release census disagree")
        return sorted(records, key=lambda record: record.tag)

    @staticmethod
    def _candidate_pages(release_json: str, ref_json: str):
        try:
            release_pages, ref_pages = json.loads(release_json), json.loads(ref_json)
            if not isinstance(release_pages, list) or any(
                not isinstance(page, list) for page in release_pages
            ) or not isinstance(ref_pages, list) or any(
                not isinstance(page, list) for page in ref_pages
            ):
                raise TypeError("candidate pages are not arrays")
            releases = [item for page in release_pages for item in page]
            refs = [item for page in ref_pages for item in page]
            if any(not isinstance(item, Mapping) for item in (*releases, *refs)):
                raise TypeError("candidate census entry is not an object")
            return releases, refs
        except (json.JSONDecodeError, TypeError) as error:
            raise PromotionError("complete candidate listing is malformed") from error

    @staticmethod
    def _candidate_records(releases, targets: Mapping[str, str]):
        records: list[CandidateReleaseRecord] = []
        for release in releases:
            tag = release.get("tag_name")
            if not isinstance(tag, str) or not tag.startswith(CANDIDATE_TAG_PREFIX):
                continue
            assets = release.get("assets")
            if not isinstance(assets, list) or any(
                not isinstance(asset, Mapping) for asset in assets
            ):
                raise PromotionError(f"release asset listing is malformed for {tag}")
            names = [asset.get("name") for asset in assets]
            draft = release.get("draft")
            target = release.get("target_commitish") if draft is True else targets.get(tag)
            if (
                any(not isinstance(name, str) or not name for name in names)
                or len(names) != len(set(names))
                or not _PRODUCER_COMMIT.fullmatch(str(target or ""))
                or (tag in targets and targets[tag] != target)
                or not isinstance(release.get("name"), str)
                or not isinstance(release.get("body"), (str, type(None)))
                or not isinstance(draft, bool)
                or not isinstance(release.get("prerelease"), bool)
            ):
                raise PromotionError(f"candidate release metadata is malformed for {tag}")
            records.append(CandidateReleaseRecord(
                tag=tag, title=str(release["name"]), notes=str(release.get("body") or ""),
                target_commit=str(target), draft=draft,
                prerelease=bool(release["prerelease"]),
                asset_names=tuple(sorted(str(name) for name in names)),
            ))
        return records

    def list_asset_names(self, tag: str) -> Sequence[str]:
        release = self._release(tag)
        assets = release.get("assets") if release is not None else None
        if not isinstance(assets, list) or any(not isinstance(item, Mapping) for item in assets):
            raise PromotionError(f"release asset listing failed for {tag}")
        names = [item.get("name") for item in assets]
        if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
            raise PromotionError(f"release asset listing is malformed for {tag}")
        return sorted(str(name) for name in names)


__all__ = ["GitHubReleaseMixin"]
