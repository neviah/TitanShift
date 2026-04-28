#!/usr/bin/env python3
"""Generate a structured CHANGELOG section from git log between two tags.

Usage:
    python scripts/gen_changelog.py --from v0.3.4 --to v0.3.5
    python scripts/gen_changelog.py --from v0.3.5          # from tag to HEAD
    python scripts/gen_changelog.py                         # last tag to HEAD

Output is printed to stdout.  Redirect to a file or pipe into release notes.

Commit prefixes recognised (conventional commits):
    feat:, fix:, docs:, chore:, refactor:, perf:, test:, build:, ci:
    Any commit that does not match a prefix lands in "Other".
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date


_SECTION_ORDER = ["feat", "fix", "perf", "refactor", "docs", "test", "build", "ci", "chore"]
_SECTION_LABELS: dict[str, str] = {
    "feat":     "### Features",
    "fix":      "### Bug Fixes",
    "perf":     "### Performance",
    "refactor": "### Refactors",
    "docs":     "### Documentation",
    "test":     "### Tests",
    "build":    "### Build",
    "ci":       "### CI",
    "chore":    "### Chores",
    "other":    "### Other",
}

_PREFIX_RE = re.compile(r"^([a-z]+)(?:\([^)]*\))?!?:\s*(.+)$", re.IGNORECASE)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[gen_changelog] git error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _last_tag() -> str:
    tag = _git("describe", "--tags", "--abbrev=0")
    if not tag:
        print("[gen_changelog] No tags found in this repository.", file=sys.stderr)
        sys.exit(1)
    return tag


def _get_log(from_ref: str, to_ref: str) -> list[tuple[str, str]]:
    """Return list of (hash, subject) for commits in the range."""
    raw = _git("log", f"{from_ref}..{to_ref}", "--oneline", "--no-merges")
    if not raw:
        return []
    entries: list[tuple[str, str]] = []
    for line in raw.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            entries.append((parts[0], parts[1]))
    return entries


def _classify(subject: str) -> tuple[str, str]:
    """Return (prefix, clean_message) for a commit subject."""
    m = _PREFIX_RE.match(subject)
    if m:
        prefix = m.group(1).lower()
        msg = m.group(2).strip()
        if prefix not in _SECTION_ORDER:
            prefix = "other"
        return prefix, msg
    return "other", subject


def _format_changelog(
    from_ref: str,
    to_ref: str,
    entries: list[tuple[str, str]],
    version: str,
) -> str:
    buckets: dict[str, list[str]] = defaultdict(list)
    for sha, subject in entries:
        prefix, msg = _classify(subject)
        buckets[prefix].append(f"- {msg} ({sha})")

    today = date.today().isoformat()
    lines: list[str] = [f"## [{version}] — {today}", ""]

    order = _SECTION_ORDER + ["other"]
    for key in order:
        items = buckets.get(key)
        if not items:
            continue
        lines.append(_SECTION_LABELS[key])
        lines.extend(items)
        lines.append("")

    if not any(buckets.values()):
        lines.append("_No changes found._")
        lines.append("")

    lines.append(f"**Full diff:** `{from_ref}..{to_ref}`")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CHANGELOG from git log")
    parser.add_argument("--from", dest="from_ref", default=None, help="Start ref/tag (exclusive)")
    parser.add_argument("--to",   dest="to_ref",   default="HEAD", help="End ref/tag (default: HEAD)")
    parser.add_argument("--version", default=None, help="Release version label (default: to_ref)")
    args = parser.parse_args()

    from_ref = args.from_ref or _last_tag()
    to_ref = args.to_ref
    version = args.version or to_ref

    entries = _get_log(from_ref, to_ref)
    output = _format_changelog(from_ref, to_ref, entries, version)
    print(output)


if __name__ == "__main__":
    main()
