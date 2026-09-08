"""Compare the actual workflow boundaries that disagreed in stable v0.4.4."""

import os
import runpy
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SELECT = runpy.run_path(str(ROOT / "python/scripts/select_build_version.py"))["select_identity"]


def workflow(name):
    return yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("raw_semver", ["0.4.4-1", "0.4.4"], ids=["before-release-tag", "after-release-tag"])
def test_main_package_and_image_identity_match_the_release_workflow(tmp_path, raw_semver):
    container = workflow("container-build-python")
    identity = next(step for step in container["jobs"]["version"]["steps"] if step.get("id") == "identity")
    release = next(step for step in workflow("release")["jobs"]["release"]["steps"] if step.get("id") == "version")
    outputs = []
    for name, step in [("container", identity), ("release", release)]:
        output = tmp_path / name
        result = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=ROOT,
            env={
                **os.environ,
                "BUILD_REF": "refs/heads/main",
                "SEMVER": raw_semver,
                "MAJOR_MINOR_PATCH": "0.4.4",
                "VERSION": "0.4.4",
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(dict(line.split("=", 1) for line in output.read_text().splitlines()))
    image, release = outputs
    assert image["semver"] == image["package_version"] == release["version"] == "0.4.4"
    assert release["tag"] == f"v{image['semver']}"


@pytest.mark.parametrize(
    "build_ref,semver,expected_package",
    [
        ("refs/heads/develop", "0.5.0-alpha.1", "0.5.0a1"),
        ("refs/pull/263/merge", "0.5.0-PullRequest263.7", "0.5.0.dev0+gitversion.50756c6c526571756573743236332e37"),
        ("refs/heads/fix/candidate", "0.5.0-fix.candidate.1", "0.5.0.dev0+gitversion.6669782e63616e6469646174652e31"),
        ("refs/heads/main-preview", "0.5.0-1", "0.5.0.dev0+gitversion.31"),
    ],
    ids=["develop-alpha", "release-pr-is-not-main", "sha-candidate", "similarly-named-branch"],
)
def test_non_main_builds_retain_their_prerelease_identity(build_ref, semver, expected_package):
    assert SELECT(build_ref, semver, "0.5.0") == (semver, expected_package)


@pytest.mark.parametrize("build_ref", ["refs/heads/main", "refs/heads/develop"])
@pytest.mark.parametrize(
    "semver,major_minor_patch",
    [
        ("0.4.4-1", "0.5.0"),
        ("0.4.4-1", "0.4.4-alpha.1"),
        ("0.4.4-1", "v0.4.4"),
        ("0.4.4-1", ""),
        ("0.4.4-a..1", "0.4.4"),
        ("0.4.4-alpha.01", "0.4.4"),
        ("${VERSION}", "0.4.4"),
    ],
    ids=[
        "different-core",
        "prerelease-core",
        "prefixed-core",
        "missing-core",
        "empty-label",
        "leading-zero",
        "unresolved",
    ],
)
def test_invalid_calculations_cannot_be_hidden_by_selecting_a_stable_version(build_ref, semver, major_minor_patch):
    with pytest.raises(ValueError):
        SELECT(build_ref, semver, major_minor_patch)


def test_validation_and_publication_consume_the_selected_identity():
    jobs = workflow("container-build-python")["jobs"]
    assert jobs["version"]["outputs"]["semver"] == "${{ steps.identity.outputs.semver }}"
    assert jobs["version"]["outputs"]["package_version"] == "${{ steps.identity.outputs.package_version }}"
    package_check = next(step for step in jobs["version"]["steps"] if "check_package.py" in step.get("run", ""))
    assert package_check["env"]["SEMVER"] == "${{ steps.identity.outputs.semver }}"
    for job in ["validate", "build-and-push"]:
        build = next(
            step for step in jobs[job]["steps"] if step.get("uses", "").startswith("docker/build-push-action@")
        )
        assert build["with"]["build-args"] == "PROVIDER_VERSION=${{ needs.version.outputs.semver }}\n"
    runtime = next(step for step in jobs["validate"]["steps"] if "EXPECTED_PACKAGE_VERSION" in step.get("env", {}))
    assert runtime["env"]["EXPECTED_PACKAGE_VERSION"] == "${{ needs.version.outputs.package_version }}"
    metadata = next(step for step in jobs["build-and-push"]["steps"] if step.get("id") == "meta")
    for field in ["labels", "annotations"]:
        assert "org.opencontainers.image.version=${{ needs.version.outputs.semver }}" in metadata["with"][field]
        assert "org.opencontainers.image.licenses=MPL-2.0" in metadata["with"][field]
    published = next(step for step in jobs["build-and-push"]["steps"] if step.get("id") == "build")
    assert published["with"]["annotations"] == "${{ steps.meta.outputs.annotations }}"
