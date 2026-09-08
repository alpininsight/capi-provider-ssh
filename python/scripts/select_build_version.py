"""Select the artifact identity from GitVersion without promoting branch builds."""

import os
import runpy
from pathlib import Path

NORMALIZE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "package_version.py"))["normalize_version"]


def select_identity(build_ref: str, semver: str, major_minor_patch: str) -> tuple[str, str]:
    package_version = NORMALIZE(semver)
    if NORMALIZE(major_minor_patch) != major_minor_patch:
        raise ValueError("MajorMinorPatch must be an unprefixed stable version")
    if semver.removeprefix("v").partition("-")[0] != major_minor_patch:
        raise ValueError("GitVersion SemVer and MajorMinorPatch identify different releases")
    if build_ref == "refs/heads/main":
        # ManualDeployment can return e.g. 0.4.4-1 before the parallel release
        # workflow creates v0.4.4. Match that workflow's stable release identity.
        return major_minor_patch, major_minor_patch
    return semver, package_version


if __name__ == "__main__":
    semver, package_version = select_identity(
        os.environ["BUILD_REF"], os.environ["SEMVER"], os.environ["MAJOR_MINOR_PATCH"]
    )
    print(f"semver={semver}\npackage_version={package_version}")
