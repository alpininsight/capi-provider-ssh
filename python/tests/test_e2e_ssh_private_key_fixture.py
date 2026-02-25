"""Regression tests for E2E SSH key fixture path handling."""

from __future__ import annotations

import pytest

from tests.e2e import conftest as e2e_conftest


def test_ssh_private_key_expands_tilde_env_path(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    key_file = home_dir / ".ssh" / "e2e_key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("fake-private-key", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("E2E_SSH_KEY_PATH", "~/.ssh/e2e_key")

    assert e2e_conftest.ssh_private_key.__wrapped__() == "fake-private-key"


def test_ssh_private_key_skip_reports_expanded_path(monkeypatch, tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("E2E_SSH_KEY_PATH", "~/.ssh/missing_key")

    with pytest.raises(pytest.skip.Exception) as exc:
        e2e_conftest.ssh_private_key.__wrapped__()

    assert str(home_dir / ".ssh" / "missing_key") in str(exc.value)
