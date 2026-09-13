#!/usr/bin/env python3
"""Publish exactly the manifest's four verified stock archives; never rebuild."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

REPOSITORY = "LancasterAgentic/openclaw-installation-artifacts"
ROOT = Path(__file__).resolve().parents[1]


class PromotionError(ValueError):
    """Only explicit messages in this module are safe to print."""


def need(value, message):
    if not value:
        raise PromotionError(message)


def manifest_rows(manifest):
    tag = manifest["release_tag"]
    need(re.fullmatch(r"installation-candidate-[0-9]+-[0-9]+", tag), "Invalid release tag")
    rows = manifest["archives"]
    need(len(rows) == 4 and {r["role"] for r in rows} == {"base", "sandbox", "browser", "hyperv-template"},
         "Expected exactly four approved stock archives")
    need(len({r["file"] for r in rows}) == 4, "Duplicate archive filename")
    for row in rows:
        need(re.fullmatch(r"[a-z0-9][a-z0-9.-]+\.(?:tar|vhdx)\.gz", row["file"]), "Invalid archive filename")
        need(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), "Invalid archive digest")
        need(type(row["bytes"]) is int and 0 < row["bytes"] < 2 * 1024**3, "Invalid archive size")
        need(row["url"] == f"https://github.com/{REPOSITORY}/releases/download/{tag}/{row['file']}",
             "Archive destination differs from approved repository")
    return rows


def signed_links(raw, rows):
    links = json.loads(raw)
    need(isinstance(links, dict) and set(links) == {r["file"] for r in rows}, "Signed links must match all four archives")
    for value in links.values():
        need(isinstance(value, str) and "\n" not in value and "\r" not in value, "Invalid signed link")
        parsed = urlsplit(value)
        need(parsed.scheme == "https" and parsed.netloc == "release-assets.githubusercontent.com"
             and parsed.path.startswith("/github-production-release-asset/") and parsed.query,
             "Signed link must address one GitHub release asset")
        # Mask each URL before invoking any subprocess. Never print errors containing URLs.
        print("::add-mask::" + value.replace("%", "%25"), flush=True)
    return links


def verify(path, row):
    need(path.stat().st_size == row["bytes"], "Archive byte count mismatch: " + row["file"])
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    need(digest == row["sha256"], "Archive checksum mismatch: " + row["file"])


def gh(*args, payload=None):
    result = subprocess.run(["gh", *args], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1200)
    need(result.returncode == 0, "GitHub operation failed: " + " ".join(args[:2]))
    return result.stdout


def main():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    rows = manifest_rows(manifest)
    need(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Unexpected publication repository")
    repo = json.loads(gh("api", "repos/" + REPOSITORY))
    need(repo["full_name"] == REPOSITORY and repo["private"] is False and repo["visibility"] == "public",
         "Publication requires the exact public artifact repository")
    links = signed_links(os.environ.pop("STOCK_ARCHIVE_SIGNED_URLS", ""), rows)
    tag = manifest["release_tag"]
    # No clobber or release deletion: an existing release requires explicit inspection.
    # Tag lookup sees published releases only. Listing includes owned drafts too.
    pages = json.loads(gh("api", f"repos/{REPOSITORY}/releases?per_page=100", "--paginate", "--slurp"))
    need(not any(release["tag_name"] == tag for page in pages for release in page), "Release already exists")
    with tempfile.TemporaryDirectory(prefix="stock-promotion-") as directory:
        paths = []
        for row in rows:
            path = Path(directory) / row["file"]
            result = subprocess.run(["curl", "--disable", "--fail", "--silent", "--show-error",
                "--proto", "=https", "--connect-timeout", "30", "--max-time", "1200",
                "--max-filesize", str(row["bytes"]), "--output", str(path), links[row["file"]]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1250)
            need(result.returncode == 0, "Signed archive download failed: " + row["file"])
            verify(path, row)
            paths.append(str(path))
            print(json.dumps({"verified": row["file"], "bytes": row["bytes"], "sha256": row["sha256"]}), flush=True)
        # All four inputs passed before any release or asset mutation.
        created = json.loads(gh("api", f"repos/{REPOSITORY}/releases", "--method", "POST", "--input", "-",
            payload=json.dumps({"tag_name": tag, "target_commitish": os.environ["GITHUB_SHA"], "draft": True,
                "prerelease": True, "name": "Verified upstream installation artifacts",
                "body": (ROOT / "README.md").read_text(encoding="utf-8")}).encode()))
        release_id = created["id"]
        need(type(release_id) is int and release_id > 0, "Created release has no valid ID")
        gh("release", "upload", tag, "--repo", REPOSITORY, *paths,
           *[str(ROOT / name) for name in ("manifest.json", "SHA256SUMS", "OPENCLAW-LICENSE", "OPENCLAW-THIRD_PARTY_NOTICES.md")])
        release = json.loads(gh("api", f"repos/{REPOSITORY}/releases/{release_id}"))
        assets = {asset["name"]: asset for asset in release["assets"]}
        for row in rows:
            asset = assets.get(row["file"], {})
            need(asset.get("size") == row["bytes"] and asset.get("digest") == "sha256:" + row["sha256"],
                 "Uploaded archive digest or size differs: " + row["file"])
        gh("api", f"repos/{REPOSITORY}/releases/{release_id}", "--method", "PATCH", "-F", "draft=false")
        print(json.dumps({"status": "published", "repository": REPOSITORY, "release_tag": tag,
                          "archives": rows, "workflow_commit": os.environ["GITHUB_SHA"]}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never serialize request/subprocess exceptions: they can contain signed links.
        detail = str(error) if isinstance(error, PromotionError) else type(error).__name__
        print("Promotion failed (" + detail + "); verified existing assets remain preserved.", file=sys.stderr)
        sys.exit(1)
