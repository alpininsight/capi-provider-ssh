"""Exercise release attribution with real diverged Git history and git-cliff."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("generate_changelog", ROOT / "python/scripts/generate_changelog.py")
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


@pytest.fixture
def history(tmp_path):
    assert shutil.which("git-cliff"), "Install git-cliff 2.14.2, matching CI, before running the isolated suite"
    repo = tmp_path / "repo"
    repo.mkdir()
    tick = 0

    def git(*args):
        nonlocal tick
        tick += 1
        date = f"2026-01-01T00:{tick // 60:02}:{tick % 60:02}+0000"
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        ).stdout.strip()

    def commit(message):
        git("commit", "--allow-empty", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-b", "main")
    git("config", "user.name", "Release history test")
    git("config", "user.email", "release-test@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "tag.gpgsign", "false")
    commit("feat: initial published provider")
    git("tag", "v0.4.5")
    # An older topic lands only after v0.4.8. Timestamp/flattened-log attribution
    # must not place its commit in an already published release.
    git("checkout", "-b", "late-topic")
    late = commit("fix: late merged transport correction")
    git("checkout", "-b", "develop", "main")
    published = {}
    for version, message in (
        ("v0.4.6", "fix: stable package identity"),
        ("v0.4.7", "chore(deps): refresh locked runtime"),
        ("v0.4.8", "docs: explain provider delivery"),
    ):
        git("checkout", "develop")
        published[version] = commit(message)
        git("checkout", "main")
        git("merge", "--no-ff", "develop", "-m", f"Merge release {version}")
        git("tag", "-a", version, "-m", f"Release {version}")
    git("update-ref", "refs/remotes/origin/main", "main")
    git("checkout", "develop")
    unreleased = commit("feat: new provider capability")
    git("merge", "--no-ff", "late-topic", "-m", "Merge late topic")
    shutil.copyfile(ROOT / "cliff.toml", repo / "cliff.toml")
    return repo, git, published, {late, unreleased}


def context(repo):
    return json.loads(
        subprocess.run(["git-cliff", "--context"], cwd=repo, check=True, capture_output=True, text=True).stdout
    )


def test_diverged_stable_history_is_rejected_before_overwriting(history):
    repo, _, _, _ = history
    output = repo / "CHANGELOG.md"
    output.write_text("existing reviewed changelog\n")
    # Reproduce the old automation's omission rather than assuming ancestry.
    assert "v0.4.8" not in {release["version"] for release in context(repo)}
    with pytest.raises(generator.HistoryError, match="v0.4.6, v0.4.7, v0.4.8"):
        generator.generate(repo, "origin/main", output)
    assert output.read_text() == "existing reviewed changelog\n"


def test_reconciliation_retains_each_release_and_only_new_work_in_unreleased(history):
    repo, git, published, unreleased = history
    git("merge", "--no-ff", "main", "-m", "chore(release): reconcile stable history")
    releases = {release["version"]: release for release in context(repo)}
    assert {commit["id"] for commit in releases[None]["commits"] if commit["group"] != "Maintenance"} == unreleased
    assert [commit["id"] for commit in releases["v0.4.6"]["commits"]] == [published["v0.4.6"]]
    assert [commit["id"] for commit in releases["v0.4.8"]["commits"]] == [published["v0.4.8"]]
    maintenance = releases["v0.4.7"]["commits"]
    assert [commit["id"] for commit in maintenance] == [published["v0.4.7"]]
    assert maintenance[0]["group"] == "Maintenance"  # omitted entries, retained boundary
    for version in published:
        assert releases[version]["commit_id"] == git("rev-parse", f"refs/tags/{version}^{{commit}}")
    generator.generate(repo, "origin/main", Path("CHANGELOG.md"))
    first = (repo / "CHANGELOG.md").read_bytes()
    text = first.decode()
    for version in published:
        assert f"releases/tag/{version}" in text
        assert f"tree/{releases[version]['commit_id']}" in text
    assert "No user-facing Conventional Commit entries." in text
    generator.generate(repo, "origin/main", Path("CHANGELOG.md"))
    assert (repo / "CHANGELOG.md").read_bytes() == first


@pytest.mark.parametrize("defect", ["missing", "identity", "unreleased", "published", "duplicate"])
def test_corrupted_release_context_is_rejected(history, defect):
    repo, git, _, _ = history
    git("merge", "--no-ff", "main", "-m", "chore(release): reconcile stable history")
    releases = context(repo)
    expected = generator.stable_releases(repo, "origin/main")
    by_version = {release["version"]: release for release in releases}
    if defect == "missing":
        releases.remove(by_version["v0.4.8"])
    elif defect == "identity":
        by_version["v0.4.8"]["commit_id"] = "0" * 40
    elif defect == "unreleased":
        by_version[None]["commits"].append(by_version["v0.4.6"]["commits"][0])
    elif defect == "published":
        by_version["v0.4.8"]["commits"].append(by_version[None]["commits"][0])
    else:
        releases.append(copy.deepcopy(by_version["v0.4.8"]))
    with pytest.raises(generator.HistoryError):
        generator.validate_context(repo, releases, expected)


def test_render_failure_preserves_existing_changelog(history, monkeypatch):
    repo, git, _, _ = history
    git("merge", "--no-ff", "main", "-m", "chore(release): reconcile stable history")
    output = repo / "CHANGELOG.md"
    output.write_text("reviewed output\n")
    actual_run = subprocess.run

    def fail_render(command, **kwargs):
        if "--from-context" in command:
            raise subprocess.CalledProcessError(1, command, stderr="render failed")
        return actual_run(command, **kwargs)

    monkeypatch.setattr(generator.subprocess, "run", fail_render)
    with pytest.raises(subprocess.CalledProcessError):
        generator.generate(repo, "origin/main", output)
    assert output.read_text() == "reviewed output\n"


def test_missing_stable_ref_fails_cli_without_writing(history):
    repo, _, _, _ = history
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "python/scripts/generate_changelog.py"),
            "--repo",
            str(repo),
            "--stable-ref",
            "origin/missing",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Changelog generation refused" in result.stderr
    assert not (repo / "CHANGELOG.md").exists()
