"""Build and inspect wheel/sdist, then rebuild and import outside Git and build env."""

import argparse
import email
import os
import runpy
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def inspect_wheel(path, expected, license_bytes):
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
        assert metadata["Version"] == expected, metadata["Version"]
        assert metadata["License-Expression"] == "MPL-2.0"
        assert metadata.get_all("License-File") == ["LICENSE"]
        assert len(metadata.get_all("Project-URL", [])) >= 5
        license_name = metadata_name.removesuffix("METADATA") + "licenses/LICENSE"
        assert archive.read(license_name) == license_bytes
        assert archive.read("capi_provider_ssh/_version.txt").decode().strip() == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="GitVersion SemVer (or stable release tag)")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    expected = runpy.run_path(str(PROJECT / "package_version.py"))["normalize_version"](args.version)
    clean_env = {key: value for key, value in os.environ.items() if key not in {"PROVIDER_VERSION", "PYTHONPATH"}}
    versioned_env = {**clean_env, "PROVIDER_VERSION": args.version}
    license_bytes = (PROJECT / "LICENSE").read_bytes()
    assert license_bytes == (PROJECT.parent / "LICENSE").read_bytes()
    offline = ["--offline"] if args.offline else []
    original = (PROJECT / "capi_provider_ssh/_version.txt").read_bytes()
    with tempfile.TemporaryDirectory(prefix="capi-artifact-check-") as temporary:
        directory = Path(temporary)
        run(
            "uv",
            "build",
            str(PROJECT),
            "--out-dir",
            str(directory / "dist"),
            *offline,
            env=versioned_env,
            cwd=directory,
        )
        wheel = next((directory / "dist").glob("*.whl"))
        sdist = next((directory / "dist").glob("*.tar.gz"))
        inspect_wheel(wheel, expected, license_bytes)
        with tarfile.open(sdist) as archive:
            archive.extractall(directory / "source", filter="data")
        source = next((directory / "source").iterdir())
        assert (source / "LICENSE").read_bytes() == license_bytes
        metadata = email.message_from_bytes((source / "PKG-INFO").read_bytes())
        assert metadata["Version"] == expected
        assert metadata.get_all("License-File") == ["LICENSE"]
        # No Git checkout and no PROVIDER_VERSION: the archive must retain identity.
        run(
            "uv",
            "build",
            str(source),
            "--wheel",
            "--out-dir",
            str(directory / "rebuilt"),
            *offline,
            env=clean_env,
            cwd=directory,
        )
        rebuilt = next((directory / "rebuilt").glob("*.whl"))
        inspect_wheel(rebuilt, expected, license_bytes)
        run("uv", "venv", "--python", sys.executable, str(directory / "venv"), *offline, env=clean_env, cwd=directory)
        interpreter = directory / "venv/bin/python"
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(interpreter),
            "--no-deps",
            str(rebuilt),
            *offline,
            env=clean_env,
            cwd=directory,
        )
        run(
            str(interpreter),
            "-c",
            (
                "import importlib.metadata, capi_provider_ssh; "
                "assert capi_provider_ssh.__version__ == importlib.metadata.version('capi-provider-ssh') == "
                f"{expected!r}"
            ),
            env=clean_env,
            cwd=directory,
        )
    assert (PROJECT / "capi_provider_ssh/_version.txt").read_bytes() == original
    print(f"Validated wheel, sdist, isolated rebuild and installed runtime: {args.version} -> {expected}")


if __name__ == "__main__":
    main()
