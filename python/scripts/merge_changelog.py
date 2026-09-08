"""Merge the expected changelog commit only after every configured check passes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class MergeBlocked(RuntimeError):
    """The current evidence does not authorize a merge."""


class PullRequestStateBlocked(MergeBlocked):
    """A mutable PR state may be settling after a concurrent merge."""


@dataclass(frozen=True)
class Policy:
    integration_id: int
    checks: tuple[str, ...]
    approval_required: bool = True

    @classmethod
    def load(cls, path: Path, *, reviews_path: Path | None = None) -> Policy:
        data = json.loads(path.read_text())
        checks = tuple(data["checks"])
        if not checks or len(set(checks)) != len(checks) or not all(isinstance(name, str) and name for name in checks):
            raise MergeBlocked("Required check names must be nonempty and unique")
        if not isinstance(data["integration_id"], int) or data["integration_id"] <= 0:
            raise MergeBlocked("A GitHub integration ID is required")
        try:
            reviews = json.loads((reviews_path or path.with_name("required-reviews.json")).read_text())
            count = reviews["required_approving_review_count"]
            flags = [
                reviews[key]
                for key in (
                    "require_code_owner_review",
                    "require_last_push_approval",
                    "require_extra_approval_for_unattributed_changes",
                )
            ]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise MergeBlocked("Explicit review policy is missing or invalid") from exc
        if type(count) is not int or not 0 <= count <= 10 or any(type(flag) is not bool for flag in flags):
            raise MergeBlocked("Explicit review policy is missing or invalid")
        return cls(data["integration_id"], checks, approval_required=count > 0 or any(flags))


class GitHub:
    def __init__(self, repository: str):
        self.repository = repository

    @staticmethod
    def command(*args: str) -> str:
        try:
            return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=45).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MergeBlocked("GitHub request failed; no merge fallback is permitted") from exc

    def api(self, path: str):
        return json.loads(self.command("api", f"repos/{self.repository}/{path}"))

    def pull_request(self, number: int) -> dict:
        return self.api(f"pulls/{number}")

    def files(self, number: int) -> list[dict]:
        # Any second file is already sufficient to reject a generated changelog PR.
        return self.api(f"pulls/{number}/files?per_page=2")

    def checks(self, sha: str) -> list[dict]:
        pages = json.loads(
            self.command(
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/commits/{sha}/check-runs?per_page=100&filter=latest",
            )
        )
        return [check for page in pages for check in page["check_runs"]]

    def review_state(self, number: int) -> dict:
        return json.loads(
            self.command("pr", "view", str(number), "--repo", self.repository, "--json", "headRefOid,reviewDecision")
        )

    def queue_merge(self, number: int, sha: str) -> None:
        self.command(
            "pr", "merge", str(number), "--repo", self.repository, "--auto", "--squash", "--match-head-commit", sha
        )

    def merge(self, number: int, sha: str) -> None:
        # GitHub's active strict rules remain the final gate if the base changes.
        self.command("pr", "merge", str(number), "--repo", self.repository, "--squash", "--match-head-commit", sha)


def validate_pull_request(pr: dict, repository: str, expected_head: str) -> None:
    if pr["head"]["sha"] != expected_head:
        raise MergeBlocked("PR head changed; a new run must validate the new commit")
    if pr["base"]["ref"] != "develop" or pr["head"]["ref"] != "chore/changelog-update":
        raise MergeBlocked("Only the generated changelog branch targeting develop may be merged")
    if (pr["head"].get("repo") or {}).get("full_name") != repository:
        raise MergeBlocked("A fork cannot supply the changelog branch")
    if pr.get("merged"):
        return
    if pr["state"] != "open" or pr.get("draft"):
        raise PullRequestStateBlocked("The changelog PR must be open and ready for review")
    if pr.get("mergeable_state") in {"behind", "dirty"}:
        raise PullRequestStateBlocked("Update the changelog branch and re-run checks before merging")


def read_validated_pull_request(github: GitHub, number: int, expected_head: str, *, sleep, interval: float) -> dict:
    pr = github.pull_request(number)
    try:
        validate_pull_request(pr, github.repository, expected_head)
    except PullRequestStateBlocked:
        # GitHub auto-merge or another maintainer may finish between our polls.
        # Retry only this read; changed identity and unsuccessful checks remain fatal.
        print(
            f"Rechecking PR #{number}: state={pr['state']}, mergeable_state={pr.get('mergeable_state')}",
            flush=True,
        )
        sleep(min(interval, 5))
        pr = github.pull_request(number)
        validate_pull_request(pr, github.repository, expected_head)
    return pr


def checks_ready(checks: list[dict], policy: Policy, expected_head: str) -> bool:
    ready = True
    for name in policy.checks:
        matches = [
            check
            for check in checks
            if check["name"] == name
            and check.get("head_sha") == expected_head
            and (check.get("app") or {}).get("id") == policy.integration_id
        ]
        if not matches:
            ready = False
            continue
        current = max(matches, key=lambda check: check["id"])
        if current["status"] != "completed":
            ready = False
        elif current.get("conclusion") != "success":
            raise MergeBlocked(f"Required check did not pass: {name} ({current.get('conclusion')})")
    return ready


def merge_when_ready(
    github: GitHub,
    number: int,
    expected_head: str,
    policy: Policy,
    *,
    timeout: float = 2400,
    interval: float = 15,
    now=time.monotonic,
    sleep=time.sleep,
) -> str | None:
    deadline = now() + timeout
    while now() < deadline:
        pr = read_validated_pull_request(github, number, expected_head, sleep=sleep, interval=interval)
        if pr.get("merged"):
            print(f"PR #{number} was already merged at the expected commit")
            return
        files = github.files(number)
        if len(files) != 1 or files[0]["filename"] != "CHANGELOG.md" or files[0]["status"] not in {"added", "modified"}:
            raise MergeBlocked("The generated PR must change only CHANGELOG.md")
        passed = checks_ready(github.checks(expected_head), policy, expected_head)
        if passed:
            review = github.review_state(number)
            if review.get("headRefOid") != expected_head:
                raise MergeBlocked("PR head changed while checking review eligibility")
            if "reviewDecision" not in review:
                raise MergeBlocked("GitHub review decision is missing")
            decision = review.get("reviewDecision")
            if decision == "REVIEW_REQUIRED":
                github.queue_merge(number, expected_head)
                print(f"PR #{number}: checks passed; auto-merge queued pending required approval")
                return "review-pending"
            if decision == "CHANGES_REQUESTED":
                print(f"PR #{number}: reviewer requested changes; leaving the PR open")
                return "changes-requested"
            if decision != "APPROVED" and (policy.approval_required or decision not in {None, ""}):
                raise MergeBlocked("Required review decision is absent; verify the active review rules")
        if passed and pr.get("mergeable") is True and pr.get("mergeable_state") == "clean":
            # Re-read after collecting evidence. The merge command also guards the head server-side.
            current = read_validated_pull_request(github, number, expected_head, sleep=sleep, interval=interval)
            if current.get("merged"):
                return
            if (
                current["base"]["sha"] == pr["base"]["sha"]
                and current.get("mergeable") is True
                and current.get("mergeable_state") == "clean"
            ):
                github.merge(number, expected_head)
                print(f"Merged PR #{number} after all required checks passed for {expected_head}")
                return
        print(f"Waiting for required checks and merge eligibility on PR #{number}: {expected_head}", flush=True)
        sleep(interval)
    raise MergeBlocked("Timed out waiting for completed checks and merge eligibility")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--timeout", type=float, default=2400)
    args = parser.parse_args()
    policy = Policy.load(Path(__file__).resolve().parents[2] / ".github" / "required-checks.json")
    try:
        outcome = merge_when_ready(GitHub(args.repo), args.pr, args.expected_head, policy, timeout=args.timeout)
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a") as output:
                output.write(f"\nChangelog PR #{args.pr}: {outcome or 'merged'}.\n")
    except MergeBlocked as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
