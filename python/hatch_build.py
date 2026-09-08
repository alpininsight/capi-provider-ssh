"""Freeze the calculated version into both distribution formats without editing source."""

from pathlib import Path
from tempfile import TemporaryDirectory

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        self.staging = TemporaryDirectory(prefix="capi-package-version-")
        version_file = Path(self.staging.name) / "_version.txt"
        version_file.write_text(self.metadata.version + "\n")
        build_data["force_include"][str(version_file)] = "capi_provider_ssh/_version.txt"

    def finalize(self, version, build_data, artifact_path):
        self.staging.cleanup()
