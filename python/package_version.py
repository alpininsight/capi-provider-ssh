"""Translate the release workflow's GitVersion SemVer into Python metadata."""

import os
import re
from pathlib import Path

SEMVER = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?")


def normalize_version(value: str) -> str:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid provider release SemVer: {value!r}")
    major, minor, patch, prerelease = match.groups()
    base = f"{major}.{minor}.{patch}"
    if not prerelease:
        return base
    parts = prerelease.split(".")
    if any(not item or (item.isdigit() and len(item) > 1 and item.startswith("0")) for item in parts):
        raise ValueError(f"Invalid SemVer prerelease: {prerelease!r}")
    standard = re.fullmatch(r"(alpha|beta|rc)\.([0-9]+)", prerelease)
    if standard:
        stage, number = standard.groups()
        return f"{base}{ {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}[stage] }{number}"
    # Branch labels have no PEP 440 ordering. Encode them losslessly as local
    # metadata on a development version, never as an apparently stable release.
    return f"{base}.dev0+gitversion.{prerelease.encode().hex()}"


def get_version() -> str:
    if "PROVIDER_VERSION" in os.environ:
        return normalize_version(os.environ["PROVIDER_VERSION"])
    return (Path(__file__).parent / "capi_provider_ssh" / "_version.txt").read_text().strip()
