"""Generate a changelog only after verifying the published release boundaries."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

STABLE_TAG = re.compile(r"v\d+\.\d+\.\d+")


class HistoryError(ValueError):
    """The current history or generated context cannot describe stable releases."""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def stable_releases(repo: Path, stable_ref: str) -> dict[str, str]:
    """Require published main history in HEAD, without merging or rewriting refs."""
    stable_sha = git(repo, "rev-parse", "--verify", f"{stable_ref}^{{commit}}")
    tags = git(repo, "tag", "--merged", stable_sha).splitlines()
    releases = {tag: git(repo, "rev-parse", f"refs/tags/{tag}^{{commit}}") for tag in tags if STABLE_TAG.fullmatch(tag)}
    ancestors = set(git(repo, "rev-list", "HEAD").splitlines())
    missing = sorted(tag for tag, sha in releases.items() if sha not in ancestors)
    if missing:
        raise HistoryError(
            f"Published release history missing from HEAD: {', '.join(missing)}. "
            "Fetch full history/tags and reconcile main through a reviewed PR before generating the changelog."
        )
    return releases


def validate_context(repo: Path, context: list[dict], expected: dict[str, str]) -> None:
    """Check immutable tag identity and graph membership, including Unreleased."""
    versions = [release["version"] for release in context if release["version"]]
    if len(versions) != len(set(versions)):
        raise HistoryError("Duplicate release versions in git-cliff context")
    by_version = {release["version"]: release for release in context}
    missing = sorted(set(expected) - set(by_version))
    if missing:
        raise HistoryError(f"git-cliff omitted published releases: {', '.join(missing)}")
    published = set()
    for version, sha in expected.items():
        release = by_version[version]
        if release["commit_id"] != sha:
            raise HistoryError(f"git-cliff source identity differs from tag {version}")
        ancestors = set(git(repo, "rev-list", sha).splitlines())
        published.update(ancestors)
        if any(commit["id"] not in ancestors for commit in release["commits"]):
            raise HistoryError(f"git-cliff attributed an unpublished commit to {version}")
    if any(commit["id"] in published for release in context if not release["version"] for commit in release["commits"]):
        raise HistoryError("git-cliff repeated an already published commit in Unreleased")


def generate(repo: Path, stable_ref: str, output: Path, *, git_cliff: str = "git-cliff") -> None:
    expected = stable_releases(repo, stable_ref)
    command = [git_cliff, "--config", str(repo / "cliff.toml")]
    context = subprocess.run([*command, "--context"], cwd=repo, check=True, capture_output=True, text=True).stdout
    validate_context(repo, json.loads(context), expected)
    # Render the exact verified context; leave the old file intact on any failure.
    with tempfile.TemporaryDirectory(prefix="provider-changelog-") as temporary:
        context_file = Path(temporary) / "context.json"
        context_file.write_text(context, encoding="utf-8")
        rendered = subprocess.run(
            [*command, "--from-context", str(context_file)], cwd=repo, check=True, capture_output=True, text=True
        ).stdout
    destination = output if output.is_absolute() else repo / output
    temporary_output = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            temporary_output = Path(stream.name)
            stream.write(rendered)
        os.replace(temporary_output, destination)
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--stable-ref", default="origin/main")
    parser.add_argument("--output", type=Path, default=Path("CHANGELOG.md"))
    args = parser.parse_args()
    try:
        generate(args.repo.resolve(), args.stable_ref, args.output)
    except (HistoryError, subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Changelog generation refused: {error}\n")


if __name__ == "__main__":
    main()
