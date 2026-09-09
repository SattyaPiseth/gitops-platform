#!/usr/bin/env python3
"""Validate local targets in tracked Markdown files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


INLINE_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^]]+]:\s*(?:<([^>]+)>|(\S+))")
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def tracked_markdown(repository_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return [repository_root / item.decode() for item in result.stdout.split(b"\0") if item]


def link_targets(line: str) -> list[str]:
    targets = [match.group(1).strip() for match in INLINE_LINK.finditer(line)]
    reference = REFERENCE_LINK.match(line)
    if reference:
        targets.append(reference.group(1) or reference.group(2))
    return targets


def normalized_target(raw_target: str) -> str:
    if raw_target.startswith("<") and raw_target.endswith(">"):
        return raw_target[1:-1]
    # Remove an optional Markdown title from an unbracketed destination.
    return re.split(r'\s+["\']', raw_target, maxsplit=1)[0]


def main() -> int:
    script_directory = Path(__file__).resolve().parent
    repository_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=script_directory,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).resolve()
    errors: list[str] = []

    for markdown_file in tracked_markdown(repository_root):
        relative_source = markdown_file.relative_to(repository_root)
        for line_number, line in enumerate(markdown_file.read_text().splitlines(), 1):
            for raw_target in link_targets(line):
                target = normalized_target(raw_target)
                if target.startswith("file://"):
                    errors.append(
                        f"{relative_source}:{line_number}: local file URI is not portable: {target}"
                    )
                    continue
                if not target or target.startswith(("#", "//")) or URI_SCHEME.match(target):
                    continue

                path_text = unquote(urlsplit(target).path)
                if not path_text:
                    continue
                candidate = (
                    repository_root / path_text.lstrip("/")
                    if path_text.startswith("/")
                    else markdown_file.parent / path_text
                ).resolve()
                try:
                    candidate.relative_to(repository_root)
                except ValueError:
                    errors.append(
                        f"{relative_source}:{line_number}: link escapes repository: {target}"
                    )
                    continue
                if not candidate.exists():
                    errors.append(
                        f"{relative_source}:{line_number}: relative link target does not exist: {target}"
                    )

    if errors:
        print("Markdown link validation failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("All tracked Markdown relative links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
