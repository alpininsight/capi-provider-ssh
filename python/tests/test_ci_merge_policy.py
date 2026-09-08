"""Exercise merge authorization and workflow configuration failure boundaries."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("merge_changelog", ROOT / "python/scripts/merge_changelog.py")
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)

REPOSITORY = "alpininsight/capi-provider-ssh"
HEAD = "a" * 40
BASE = "b" * 40
POLICY = guard.Policy(15368, ("quality", "lifecycle"))


def pull_request(**changes):
    result = {
        "state": "open",
        "merged": False,
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "base": {"ref": "develop", "sha": BASE},
        "head": {"ref": "chore/changelog-update", "sha": HEAD, "repo": {"full_name": REPOSITORY}},
    }
    result.update(changes)
    return result


def check_runs(**changes):
    return [
        {
            "id": number,
            "name": name,
            "head_sha": HEAD,
            "app": {"id": POLICY.integration_id},
            "status": "completed",
            "conclusion": "success",
            **changes,
        }
        for number, name in enumerate(POLICY.checks, start=1)
    ]


class Clock:
    def __init__(self):
        self.elapsed = 0

    def now(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


class GitHub:
    repository = REPOSITORY

    def __init__(self, *, prs=None, checks=None, files=None):
        self.prs = prs or [pull_request()]
        self.results = checks if checks is not None else [check_runs()]
        self.changed_files = files if files is not None else [{"filename": "CHANGELOG.md", "status": "modified"}]
        self.merges = []
        self.checked_heads = []

    def pull_request(self, number):
        return self.prs.pop(0) if len(self.prs) > 1 else self.prs[0]

    def checks(self, sha):
        self.checked_heads.append(sha)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    def files(self, number):
        return self.changed_files

    def merge(self, number, sha):
        self.merges.append((number, sha))


def run(github, *, timeout=3):
    clock = Clock()
    guard.merge_when_ready(github, 123, HEAD, POLICY, timeout=timeout, interval=1, now=clock.now, sleep=clock.sleep)
    return clock


def test_merges_only_expected_commit_after_all_required_checks():
    github = GitHub()
    run(github)
    assert github.merges == [(123, HEAD)]
    assert github.checked_heads == [HEAD]


@pytest.mark.parametrize("state", ["queued", "in_progress", "waiting", "pending"])
def test_pending_check_waits_for_completion(state):
    github = GitHub(checks=[check_runs(status=state, conclusion=None), check_runs()])
    clock = run(github)
    assert clock.elapsed == 1
    assert github.merges == [(123, HEAD)]


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "timed_out", "action_required", "skipped", "neutral", None]
)
def test_unsuccessful_required_check_blocks_merge(conclusion):
    github = GitHub(checks=[check_runs(conclusion=conclusion)])
    with pytest.raises(guard.MergeBlocked, match="Required check did not pass"):
        run(github)
    assert not github.merges


@pytest.mark.parametrize("checks", [[], check_runs()[:1], check_runs(app={"id": 1}), check_runs(head_sha="c" * 40)])
def test_missing_untrusted_or_wrong_commit_evidence_cannot_authorize_merge(checks):
    github = GitHub(checks=[checks])
    with pytest.raises(guard.MergeBlocked, match="Timed out"):
        run(github)
    assert not github.merges


def test_new_pending_attempt_prevents_reusing_old_success():
    pending = {**check_runs()[0], "id": 99, "status": "in_progress", "conclusion": None}
    github = GitHub(checks=[[pending, *check_runs()]])
    with pytest.raises(guard.MergeBlocked, match="Timed out"):
        run(github)
    assert not github.merges


def test_successful_rerun_supersedes_cancelled_attempt():
    old = [{**check, "conclusion": "cancelled"} for check in check_runs()]
    current = [{**check, "id": check["id"] + 10} for check in check_runs()]
    github = GitHub(checks=[[*old, *current]])
    run(github)
    assert github.merges == [(123, HEAD)]


def test_unrelated_scheduled_check_is_not_a_required_pr_lane():
    unrelated = {**check_runs()[0], "name": "external-nightly", "status": "queued", "conclusion": None}
    github = GitHub(checks=[[unrelated, *check_runs()]])
    run(github)
    assert github.merges == [(123, HEAD)]


@pytest.mark.parametrize("state", ["behind", "dirty"])
def test_outdated_or_conflicting_branch_stops_for_new_checks(state):
    github = GitHub(prs=[pull_request(mergeable_state=state)])
    with pytest.raises(guard.MergeBlocked, match="Update the changelog branch"):
        run(github)
    assert not github.merges


@pytest.mark.parametrize("state", ["blocked", "unknown", "unstable"])
def test_nonclean_merge_state_cannot_be_bypassed_by_successful_checks(state):
    github = GitHub(prs=[pull_request(mergeable_state=state)])
    with pytest.raises(guard.MergeBlocked, match="Timed out"):
        run(github)
    assert not github.merges


def test_unknown_mergeability_is_rechecked():
    github = GitHub(prs=[pull_request(mergeable=None, mergeable_state="unknown"), pull_request()])
    assert run(github).elapsed == 1
    assert github.merges == [(123, HEAD)]


def test_changed_head_after_successful_checks_is_rejected():
    changed = copy.deepcopy(pull_request())
    changed["head"]["sha"] = "c" * 40
    github = GitHub(prs=[pull_request(), changed])
    with pytest.raises(guard.MergeBlocked, match="PR head changed"):
        run(github)
    assert not github.merges


def test_base_moving_between_reads_restarts_evidence_collection():
    changed = copy.deepcopy(pull_request())
    changed["base"]["sha"] = "c" * 40
    github = GitHub(prs=[pull_request(), changed, changed])
    clock = run(github)
    assert clock.elapsed == 1
    assert github.checked_heads == [HEAD, HEAD]
    assert github.merges == [(123, HEAD)]


@pytest.mark.parametrize("change", [{"draft": True}, {"state": "closed"}])
def test_unreviewable_pr_cannot_merge(change):
    github = GitHub(prs=[pull_request(**change)])
    with pytest.raises(guard.MergeBlocked, match="open and ready"):
        run(github)
    assert not github.merges


@pytest.mark.parametrize("field,value", [("base", "main"), ("head", "fix/unrelated")])
def test_branch_routing_is_enforced(field, value):
    pr = pull_request()
    pr[field]["ref"] = value
    github = GitHub(prs=[pr])
    with pytest.raises(guard.MergeBlocked, match="Only the generated changelog"):
        run(github)
    assert not github.merges


def test_fork_cannot_supply_generated_changes():
    pr = pull_request()
    pr["head"]["repo"]["full_name"] = "someone/capi-provider-ssh"
    github = GitHub(prs=[pr])
    with pytest.raises(guard.MergeBlocked, match="fork"):
        run(github)
    assert not github.merges


@pytest.mark.parametrize(
    "files",
    [
        [],
        [{"filename": "README.md", "status": "modified"}],
        [{"filename": "CHANGELOG.md", "status": "removed"}],
        [{"filename": "CHANGELOG.md", "status": "modified"}, {"filename": "python/Dockerfile", "status": "modified"}],
    ],
)
def test_non_changelog_changes_block_automation(files):
    github = GitHub(files=files)
    with pytest.raises(guard.MergeBlocked, match="only CHANGELOG.md"):
        run(github)
    assert not github.merges


def test_previously_merged_expected_head_is_idempotent():
    github = GitHub(prs=[pull_request(state="closed", merged=True)])
    run(github)
    assert not github.merges
    assert not github.checked_heads


def test_server_rejection_has_no_merge_fallback(monkeypatch):
    calls = []

    def reject(args, **kwargs):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args, stderr="sensitive diagnostics")

    monkeypatch.setattr(subprocess, "run", reject)
    with pytest.raises(guard.MergeBlocked, match="no merge fallback") as exc:
        guard.GitHub(REPOSITORY).merge(123, HEAD)
    assert len(calls) == 1
    assert calls[0][-2:] == ["--match-head-commit", HEAD]
    assert "--admin" not in calls[0] and "--auto" not in calls[0]
    assert "sensitive diagnostics" not in str(exc.value)


def test_policy_covers_real_pr_job_names():
    policy = guard.Policy.load(ROOT / ".github/required-checks.json")
    actual = set()
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        if "pull_request" not in workflow.get("on", {}):
            continue
        for job_id, job in workflow["jobs"].items():
            if job.get("if"):
                continue  # Publication is conditional and intentionally not a PR gate.
            name = job.get("name", job_id)
            matrix = job.get("strategy", {}).get("matrix", {})
            if matrix:
                assert set(matrix) == {"python-version"}, "Review required check names when changing the matrix"
                actual.update(f"{name} ({version})" for version in matrix["python-version"])
            else:
                actual.add(name)
    assert set(policy.checks) == actual


@pytest.mark.parametrize("checks", [[], ["quality", "quality"], [""]])
def test_empty_or_ambiguous_policy_is_rejected(tmp_path, checks):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"integration_id": 15368, "checks": checks}))
    with pytest.raises(guard.MergeBlocked, match="nonempty and unique"):
        guard.Policy.load(path)


@pytest.mark.parametrize("missing", ["E2E_SSH_HOST", "E2E_SSH_PRIVATE_KEY", "E2E_SSH_KNOWN_HOSTS", None])
def test_external_e2e_preflight_runs_before_checkout_without_disclosing_secrets(tmp_path, missing):
    workflow = yaml.load((ROOT / ".github/workflows/e2e-ssh.yml").read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["e2e-ssh"]
    step = job["steps"][0]
    # Before checkout, the project's python/ directory does not exist.
    directory = step.get("working-directory", job["defaults"]["run"]["working-directory"])
    cwd = tmp_path if directory == "${{ runner.temp }}" else tmp_path / directory
    env = {
        "E2E_SSH_HOST": "test.invalid",
        "E2E_SSH_PRIVATE_KEY": "private-test-value",
        "E2E_SSH_KNOWN_HOSTS": "trust-value",
    }
    if missing:
        del env[missing]
    result = subprocess.run(["/bin/bash", "-c", step["run"]], cwd=cwd, env=env, capture_output=True, text=True)
    assert result.returncode == (1 if missing else 0)
    assert "private-test-value" not in result.stdout + result.stderr
    assert "trust-value" not in result.stdout + result.stderr
    if missing:
        assert missing in result.stdout


@pytest.mark.parametrize(
    "ref,existing,annotated,expected",
    [
        ("main", None, False, "v0.5.0"),
        ("main", "current", False, "v0.5.0"),
        ("main", "current", True, "v0.5.0"),
        ("main", "previous", False, ""),
        ("main", "previous", True, ""),
        ("main", "branch-name", False, "v0.5.0"),
        ("develop", "previous", False, "0.5.0-alpha.1"),
        ("fix/candidate", None, False, ""),
    ],
    ids=[
        "before-release",
        "release-first",
        "annotated-release-first",
        "older-release",
        "older-annotated",
        "branch-is-not-tag",
        "develop",
        "candidate",
    ],
)
def test_container_version_tag_is_independent_of_release_workflow_order(tmp_path, ref, existing, annotated, expected):
    workflow = yaml.load((ROOT / ".github/workflows/container-build-python.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(step for step in workflow["jobs"]["build-and-push"]["steps"] if step.get("id") == "version")

    def git(*args):
        return subprocess.run(
            [
                "git",
                "-c",
                "user.name=CI Test",
                "-c",
                "user.email=ci@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "--quiet")
    git("commit", "--quiet", "--allow-empty", "-m", "previous release")
    previous = git("rev-parse", "HEAD")
    git("commit", "--quiet", "--allow-empty", "-m", "release candidate")
    current = git("rev-parse", "HEAD")
    if existing == "branch-name":
        git("branch", "v0.5.0", previous)
    elif existing:
        target = current if existing == "current" else previous
        args = ["tag", "v0.5.0", target]
        if annotated:
            args.extend(["--annotate", "--message", "release"])
        git(*args)

    output = tmp_path / "github-output"
    result = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "BUILD_REF": f"refs/heads/{ref}",
            "BUILD_SHA": current,
            "MAJOR_MINOR_PATCH": "0.5.0",
            "SEMVER": "0.5.0-alpha.1",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"tag={expected}\n"
