"""Release identity remains stable, including branch prereleases."""

import runpy
from pathlib import Path

import pytest
from packaging.version import Version

NORMALIZE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "package_version.py"))["normalize_version"]


@pytest.mark.parametrize(
    "semver, expected",
    [
        ("v0.4.3", "0.4.3"),
        ("0.4.4", "0.4.4"),
        ("0.5.0-alpha.12", "0.5.0a12"),
        ("0.5.0-beta.2", "0.5.0b2"),
        ("1.0.0-rc.1", "1.0.0rc1"),
    ],
)
def test_release_versions_match_pep440(semver, expected):
    assert NORMALIZE(semver) == expected
    assert str(Version(expected)) == expected


def test_branch_versions_are_lossless_development_versions():
    labels = ["fix-cleanup.3", "fix.cleanup.3", "Fix.cleanup.3", "preview"]
    versions = [NORMALIZE(f"0.5.0-{label}") for label in labels]
    assert len(set(versions)) == len(labels)
    for label, version in zip(labels, versions, strict=True):
        assert Version(version).is_devrelease
        assert bytes.fromhex(version.split("gitversion.")[1]).decode() == label


@pytest.mark.parametrize(
    "invalid", ["", "v0.4", "0.4.03", "0.4.3-alpha.01", "0.4.3-a..1", "0.4.3; echo nope", "${VERSION}"]
)
def test_invalid_release_identity_fails_closed(invalid):
    with pytest.raises(ValueError):
        NORMALIZE(invalid)


def test_package_license_matches_canonical_repository_license():
    root = Path(__file__).resolve().parents[2]
    assert (root / "python/LICENSE").read_bytes() == (root / "LICENSE").read_bytes()
