#!/usr/bin/env python3
"""Fail when a workflow job can run on a GitHub-hosted runner (Alex 2026-10-27, restated 2026-11-16: no GitHub Actions minutes on GitHub's own hosts; our CI runs on our own runners).

    python scripts/hosted_label_guard.py [WORKFLOW_DIR ...]      (default: .github/workflows)
    python scripts/hosted_label_guard.py --selftest             (the guard can fail: doctored workflows must be caught, the allowed forms must pass)

Every `runs-on:` value must contain `self-hosted` and none of ubuntu-/windows-/macos-/-latest. A hosted fallback behind a variable or a condition, `${{ matrix.os }}`, `${{ inputs.x }}` and the
group/labels form count as hosted. A comment never excuses a job (the old `# hosted-ok` mark is gone). The only exception is a line in .github/hosted-allowed.txt (next to the workflow
directory): `<workflow file name> <reason>` exempts that whole file, `<workflow file name>:<job id> <reason>` one job; `#` lines are comments. An entry is temporary: its reason says what removes it.
The same file is used in the ebms-mcp, openclaw, purchasing and website repos; the app has infra/ci/no_hosted_runners.py (same rule, same allowlist file). Stdlib only."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

HOSTED = re.compile(r"ubuntu-|windows-|macos-|-latest\b", re.I)
JOB = re.compile(r"^  ([\w-]+):\s*(#.*)?$")


def strip_comment(line: str) -> str:
    """Drop a trailing `# comment` that is not inside a quoted string."""
    out, quote = [], ""
    for ch in line:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out)


def violations(path: Path) -> list[tuple[str, str]]:
    """(job id, message) for every runs-on of the file that is not on the pool."""
    lines = path.read_text(encoding="utf-8").splitlines()
    found, job, in_jobs = [], "", False
    for i, raw in enumerate(lines):
        if re.match(r"^jobs:\s*$", raw):
            in_jobs = True
        elif in_jobs and (m := JOB.match(raw)):
            job = m.group(1)
        m = re.match(r"\s*runs-on:\s*(.*)$", strip_comment(raw))
        if not m:
            continue
        v, j = m.group(1).strip(), i + 1
        while v == "" and j < len(lines) and lines[j].lstrip().startswith("-"):   # the list form
            v += " " + strip_comment(lines[j]).strip()
            j += 1
        if HOSTED.search(v) or "self-hosted" not in v:
            found.append((job, f"{path.as_posix()}:{i + 1}: job '{job}' can run on a GitHub-hosted runner: runs-on: {v[:120]}"))
    return found


def allowlist(wf_dir: Path) -> set[str]:
    f = wf_dir.parent / "hosted-allowed.txt"
    if not f.exists():
        return set()
    return {ln.split()[0] for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


def scan(wf_dir: Path) -> list[str]:
    ok, bad = allowlist(wf_dir), []
    for f in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        if f.name in ok:
            continue
        bad += [msg for job, msg in violations(f) if f"{f.name}:{job}" not in ok]
    return bad


def selftest() -> int:
    nl = chr(10)
    pool = "[self-hosted, lancaster-ci]"
    cases = [   # (runs-on text after `runs-on:` ; must be flagged)
        (" ubuntu-latest", True), (" ubuntu-24.04   # hosted-ok: x86 image build", True), (" windows-2022", True), (" macos-14", True), (" [ubuntu-latest]", True),
        (" ${{ matrix.os }}", True), (" ${{ inputs.runner }}", True), (" my-large-runners", True),
        (" ${{ vars.CI_RUNNER == 'hosted' && 'ubuntu-latest' || fromJSON('[\"self-hosted\",\"lancaster-ci\"]') }}", True),
        (nl + "      - ubuntu-latest", True), (nl + "      group: big" + nl + "      labels: x", True),
        (" " + pool, False), (" [self-hosted, lancaster-ci, X64]", False), (" ${{ fromJSON(vars.CI_FAST_RUNNER || '[\"self-hosted\",\"lancaster-ci\"]') }}", False),
        (nl + "      - self-hosted" + nl + "      - lancaster-ci", False), (" [self-hosted, lancaster-ci]   # not ubuntu-latest", False),
    ]
    bad = 0
    for text, flagged in cases:
        with tempfile.TemporaryDirectory() as d:
            wf = Path(d) / "workflows"
            wf.mkdir()
            (wf / "w.yml").write_text("jobs:" + nl + "  j:" + nl + "    runs-on:" + text + nl, encoding="utf-8")
            if bool(scan(wf)) != flagged:
                bad += 1
                print(f"SELFTEST BAD flagged={not flagged} expected={flagged}: runs-on:{text!r}")
    # the allowlist: a whole file, one job, and nothing else
    body = "jobs:" + nl + "  a:" + nl + "    runs-on: windows-latest" + nl + "  b:" + nl + "    runs-on: windows-latest" + nl
    for allow, expect in [("", 4), ("w.yml TEMPORARY until the Windows runner is up", 2), ("w.yml:a TEMPORARY until the Windows runner is up", 3), ("# w.yml only a comment", 4),
                          ("w.yml:a x" + nl + "w.yml:b x", 2), ("other.yml x", 4)]:
        with tempfile.TemporaryDirectory() as d:
            wf = Path(d) / "workflows"
            wf.mkdir()
            (wf / "w.yml").write_text(body, encoding="utf-8")
            (wf / "v.yml").write_text(body, encoding="utf-8")
            (Path(d) / "hosted-allowed.txt").write_text(allow + nl, encoding="utf-8")
            if len(scan(wf)) != expect:
                bad += 1
                print(f"SELFTEST BAD allowlist {allow!r}: {len(scan(wf))} flagged, expected {expect}")
    if bad:
        return 1
    print(f"PASS selftest: {sum(1 for _, x in cases if x)} hosted forms flagged, {sum(1 for _, x in cases if not x)} pool forms pass, the allowlist exempts only the named file or job")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--selftest"]:
        return selftest()
    bad = []
    for d in [Path(a) for a in argv[1:]] or [Path(".github/workflows")]:
        bad += scan(d)
    for b in bad:
        print("FAIL " + b)
    if bad:
        print(f"{len(bad)} job(s) can run on a GitHub-hosted runner (billed minutes): use [self-hosted, lancaster-ci]; a job that truly cannot gets a temporary line in .github/hosted-allowed.txt")
        return 1
    print("ALL PASS no GitHub-hosted runner labels")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
