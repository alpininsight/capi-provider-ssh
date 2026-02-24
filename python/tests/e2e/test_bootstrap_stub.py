"""E2E tests for stub bootstrap script execution on a real SSH target."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


class TestBootstrapStub:
    """Validate script upload and execution via SSH (stub scripts, no real kubeadm)."""

    async def test_upload_and_run_stub_bootstrap(self, ssh_connection):
        """Upload a stub bootstrap script, execute it, and verify the marker file."""
        script = "#!/bin/bash\necho 'bootstrap-ok' > /tmp/capi-e2e-bootstrap-marker\n"
        await ssh_connection.upload(script, "/tmp/capi-e2e-bootstrap.sh")

        result = await ssh_connection.execute("bash /tmp/capi-e2e-bootstrap.sh")
        assert result.exit_code == 0
        assert result.success is True

        verify = await ssh_connection.execute("cat /tmp/capi-e2e-bootstrap-marker")
        assert verify.exit_code == 0
        assert "bootstrap-ok" in verify.stdout

    async def test_stub_bootstrap_failure(self, ssh_connection):
        """A stub script that exits non-zero is reported correctly."""
        script = "#!/bin/bash\nexit 1\n"
        await ssh_connection.upload(script, "/tmp/capi-e2e-fail-script.sh")

        result = await ssh_connection.execute("bash /tmp/capi-e2e-fail-script.sh")
        assert result.exit_code == 1
        assert result.success is False

    async def test_cleanup_removes_artifacts(self, ssh_connection):
        """Cleanup command removes all /tmp/capi-e2e-* marker files."""
        # Create several marker files
        for i in range(3):
            await ssh_connection.upload(f"marker-{i}", f"/tmp/capi-e2e-cleanup-{i}")

        # Verify they exist
        result = await ssh_connection.execute("ls /tmp/capi-e2e-cleanup-*")
        assert result.exit_code == 0

        # Run cleanup
        result = await ssh_connection.execute("rm -f /tmp/capi-e2e-*")
        assert result.exit_code == 0

        # Verify they're gone
        result = await ssh_connection.execute("ls /tmp/capi-e2e-cleanup-* 2>/dev/null")
        assert result.exit_code != 0  # ls returns non-zero when no files match
