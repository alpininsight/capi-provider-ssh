"""Regression tests for container runtime startup behavior."""

from pathlib import Path

import kopf
import pytest

from capi_provider_ssh.main import configure

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_docker_entrypoint_uses_kopf_directly() -> None:
    """Regression guard for a previously broken ENTRYPOINT.

    ENTRYPOINT previously used ``uv run``, which writes to ``~/.cache/uv`` at
    startup. This can fail in hardened pods with read-only root filesystem and
    non-root users.
    """
    content = DOCKERFILE.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    entrypoint = next((line for line in lines if line.startswith("ENTRYPOINT")), "")
    assert entrypoint, "Dockerfile must define an ENTRYPOINT."
    assert '"uv", "run"' not in entrypoint, (
        "Regression guard: ENTRYPOINT must not use `uv run` because it may write to `~/.cache/uv` at runtime."
    )
    assert '"kopf", "run"' in entrypoint, "ENTRYPOINT must execute kopf directly from the venv."
    assert "--standalone" not in entrypoint, "Standalone disables multi-replica coordination."
    assert '"--all-namespaces"' in entrypoint, (
        "Regression guard: the provider owns cluster-scoped CAPI resources, so Kopf scope must stay explicit."
    )
    assert "--liveness=http://0.0.0.0:8080/healthz" in entrypoint, (
        "Regression guard: probes target /healthz on 8080, so Kopf liveness must be enabled in ENTRYPOINT."
    )
    assert '"-m", "capi_provider_ssh.main"' in entrypoint, (
        "Regression guard: ENTRYPOINT must run module mode to avoid brittle script-path imports."
    )
    assert "capi_provider_ssh/main.py" not in entrypoint, (
        "Regression guard: do not execute package module via file path in ENTRYPOINT."
    )


def test_dockerfile_exports_venv_bin_on_path() -> None:
    """Regression guard for PATH wiring after removing ``uv run``."""
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENV PATH="/app/.venv/bin:${PATH}"' in content, (
        "Regression guard: runtime must use build-time venv binaries to avoid needing `uv run`."
    )


def test_startup_configures_api_and_mandatory_distinct_peers(monkeypatch):
    from unittest.mock import Mock

    load = Mock()
    monkeypatch.setattr("kubernetes.config.load_incluster_config", load)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "test-api")
    monkeypatch.setenv("SSH_PROVIDER_HA", "true")
    priorities = []
    for uid in ("pod-a", "pod-b"):
        monkeypatch.setenv("POD_UID", uid)
        settings = kopf.OperatorSettings()
        configure(settings)
        assert settings.peering.name == "capi-provider-ssh"
        assert settings.peering.mandatory and not settings.peering.standalone
        priorities.append(settings.peering.priority)
    assert priorities[0] != priorities[1]
    assert load.call_count == 2


def test_local_startup_requires_explicit_context(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("KUBECONFIG", raising=False)
    with pytest.raises(RuntimeError, match="KUBECONFIG explicitly"):
        configure(kopf.OperatorSettings())
