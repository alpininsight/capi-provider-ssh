"""Regression tests for container runtime startup behavior."""

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_docker_entrypoint_uses_kopf_directly() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    entrypoint = next((line for line in lines if line.startswith("ENTRYPOINT")), "")
    assert entrypoint, "Dockerfile must define an ENTRYPOINT."
    assert '"uv", "run"' not in entrypoint, (
        "Regression guard: ENTRYPOINT previously used `uv run`, which writes to "
        "`~/.cache/uv` and can fail in hardened pods (`readOnlyRootFilesystem: true`, non-root)."
    )
    assert '"kopf", "run"' in entrypoint, "ENTRYPOINT must execute kopf directly from the venv."
    assert '--liveness=http://0.0.0.0:8080/healthz' in entrypoint, (
        "Regression guard: probes target /healthz on 8080, but this broke before when Kopf liveness "
        "endpoint was not enabled in ENTRYPOINT."
    )


def test_dockerfile_exports_venv_bin_on_path() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENV PATH="/app/.venv/bin:${PATH}"' in content, (
        "Regression guard: runtime must use build-time venv binaries to avoid needing `uv run`."
    )
