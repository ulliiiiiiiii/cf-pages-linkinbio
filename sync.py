#!/usr/bin/env python3
"""Check the profiles in profiles/*.json and write them into the KV namespace the Pages Function reads.

    python3 sync.py --dry-run     check and show what would be written
    python3 sync.py               write every profile (one bulk request per 1,000 profiles)
    python3 sync.py --prune       also delete profiles from KV that no longer exist here

The file name is the address: profiles/jane-doe.json becomes /jane-doe. Needs CLOUDFLARE_API_TOKEN (Workers KV
Storage: Edit), CLOUDFLARE_ACCOUNT_ID and KV_NAMESPACE_ID in the environment. Python standard library only."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
FIELDS = {"name", "title", "bio", "avatar", "accent", "links"}
BATCH = 1000


class SyncError(RuntimeError):
    """A Cloudflare call failed. Never contains the token."""


def _url_ok(value, schemes=("https", "mailto")) -> bool:
    parts = urllib.parse.urlsplit(str(value or ""))
    return parts.scheme in schemes and bool(parts.netloc or parts.scheme == "mailto" and parts.path)


def check(slug: str, profile) -> list[str]:
    """Problems of one profile, as sentences; empty if it is fine."""
    if not SLUG.match(slug):
        return [f"{slug}: the file name must be lower-case letters, digits and dashes (it becomes the address)"]
    if not isinstance(profile, dict):
        return [f"{slug}: the file must hold one JSON object"]
    problems = [f"{slug}: unknown field {key!r}" for key in sorted(set(profile) - FIELDS)]
    name = profile.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        problems.append(f"{slug}: name is required, at most 80 characters")
    for key, limit in (("title", 120), ("bio", 300)):
        if key in profile and (not isinstance(profile[key], str) or len(profile[key]) > limit):
            problems.append(f"{slug}: {key} must be text of at most {limit} characters")
    if "accent" in profile and not COLOR.match(str(profile["accent"])):
        problems.append(f"{slug}: accent must look like #d9480f")
    if "avatar" in profile and not _url_ok(profile["avatar"], ("https",)):
        problems.append(f"{slug}: avatar must be an https address")
    links = profile.get("links", [])
    if not isinstance(links, list) or len(links) > 30:
        problems.append(f"{slug}: links must be a list of at most 30 entries")
        links = []
    for i, link in enumerate(links, start=1):
        if not isinstance(link, dict) or not _url_ok(link.get("url")):
            problems.append(f"{slug}: link {i} needs an https or mailto url")
        elif not isinstance(link.get("label", ""), str) or len(link.get("label", "")) > 80:
            problems.append(f"{slug}: link {i} label must be text of at most 80 characters")
    return problems


def load(folder: Path) -> tuple[dict[str, dict], list[str]]:
    profiles, problems = {}, []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{path.stem}: not readable as JSON ({exc})")
            continue
        found = check(path.stem, data)
        problems += found
        if not found:
            profiles[path.stem] = data
    return profiles, problems


class KV:
    def __init__(self, account: str, namespace: str, token: str, opener=None) -> None:
        self.base = f"{API}/accounts/{account}/storage/kv/namespaces/{namespace}"
        self._token = token
        self._opener = opener or urllib.request.build_opener()

    def _call(self, method: str, path: str, body=None, params: dict | None = None) -> dict:
        url = self.base + path + (f"?{urllib.parse.urlencode(params)}" if params else "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=60) as resp:
                answer = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                answer = json.loads(exc.read())
            except ValueError:
                raise SyncError(f"{method} {path}: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise SyncError(f"Cloudflare not reachable ({type(exc).__name__})") from None
        if not answer.get("success"):
            errors = "; ".join(f"{e.get('code')} {e.get('message')}" for e in answer.get("errors") or [])
            raise SyncError(f"{method} {path}: {errors or 'failed'}")
        return answer

    def write(self, profiles: dict[str, dict]) -> None:
        pairs = [{"key": slug, "value": json.dumps(p, ensure_ascii=False)} for slug, p in sorted(profiles.items())]
        for start in range(0, len(pairs), BATCH):
            self._call("PUT", "/bulk", pairs[start:start + BATCH])

    def keys(self) -> list[str]:
        names, cursor = [], ""
        while True:
            answer = self._call("GET", "/keys", params={"limit": 1000} | ({"cursor": cursor} if cursor else {}))
            names += [k["name"] for k in answer.get("result") or []]
            cursor = (answer.get("result_info") or {}).get("cursor") or ""
            if not cursor:
                return names

    def delete(self, keys: list[str]) -> None:
        for start in range(0, len(keys), BATCH):
            self._call("POST", "/bulk/delete", keys[start:start + BATCH])


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, opener=None) -> int:
    parser = argparse.ArgumentParser(description="Check link profiles and write them into Workers KV.")
    parser.add_argument("--profiles", type=Path, default=Path(__file__).resolve().parent / "profiles")
    parser.add_argument("--dry-run", action="store_true", help="check and show, write nothing")
    parser.add_argument("--prune", action="store_true", help="delete profiles from KV that are not in the folder")
    args = parser.parse_args(argv)
    settings: Mapping[str, str] = os.environ if env is None else env
    profiles, problems = load(args.profiles)
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    if problems:
        return 1
    for slug, p in sorted(profiles.items()):
        print(f"/{slug}: {p['name']}, {len(p.get('links', []))} links")
    if args.dry_run:
        print(f"{len(profiles)} profile(s) checked, nothing written")
        return 0
    missing = [k for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "KV_NAMESPACE_ID") if not settings.get(k)]
    if missing:
        print(f"set {', '.join(missing)} in the environment", file=sys.stderr)
        return 1
    kv = KV(settings["CLOUDFLARE_ACCOUNT_ID"], settings["KV_NAMESPACE_ID"], settings["CLOUDFLARE_API_TOKEN"], opener)
    try:
        kv.write(profiles)
        print(f"{len(profiles)} profile(s) written")
        if args.prune:
            gone = sorted(set(kv.keys()) - set(profiles))
            kv.delete(gone)
            print(f"{len(gone)} profile(s) deleted" + (f": {', '.join(gone)}" if gone else ""))
    except SyncError as exc:
        print(f"sync: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
