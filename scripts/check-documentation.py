#!/usr/bin/env python3
"""Check local Markdown links and reviewed same-organization GitHub references."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK = re.compile(r"!?\[[^\n]*?\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
GITHUB_URL = re.compile(r"https?://github\.com/([^/\s<>\[\]()]+)/([^/\s<>\[\]()?#]+)")


def prose(text: str) -> str:
    """Ignore fenced examples when looking for actual headings and local links."""
    result = []
    fence = ""
    size = 0
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if not fence:
                fence, size = marker[0], len(marker)
            elif marker[0] == fence and len(marker) >= size:
                fence = ""
            continue
        if not fence:
            result.append(line)
    return "\n".join(result)


def heading_ids(text: str) -> set[str]:
    counts: dict[str, int] = {}
    result = set()
    for line in prose(text).splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if not match:
            continue
        title = re.sub(r"<[^>]*>", "", match[1]).lower()
        title = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\s-]", "", title).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    result.update(re.findall(r'<a\s+(?:name|id)=["\']([^"\']+)', text))
    return result


def check_documentation(root: Path, files: list[Path], policy: dict) -> list[str]:
    errors = []
    root = root.resolve()
    allowed = {name.lower() for name in policy["publicRepositories"]}
    organization = policy["organization"].lower()
    for path in files:
        source = path.read_text(encoding="utf-8")
        label = str(path.relative_to(root))
        # Scan fenced examples too: an internal URL is still public when quoted.
        for owner, repository in GITHUB_URL.findall(source):
            name = f"{owner}/{repository.removesuffix('.git')}".lower()
            if owner.lower() == organization and name not in allowed:
                errors.append(f"{label}: unreviewed organization repository {name}")
        if path.suffix != ".md":
            continue
        for match in LINK.finditer(prose(source)):
            url = urlsplit(match[1].strip("<>"))
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if not target.is_relative_to(root):
                errors.append(f"{label}: link escapes repository: {match[1]}")
            elif not target.exists():
                errors.append(f"{label}: missing local target: {match[1]}")
            elif (
                url.fragment
                and target.suffix == ".md"
                and unquote(url.fragment) not in heading_ids(target.read_text())
            ):
                errors.append(f"{label}: missing heading: {match[1]}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    files = sorted(
        {
            root / name
            for name in names
            if (name.endswith(".md") or name == "context7.json")
            and (root / name).is_file()
        }
    )
    policy = json.loads((root / ".github/public-documentation.json").read_text())
    errors = check_documentation(root, files, policy)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(
        f"Documentation links and public-reference policy passed ({len(files)} files)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
