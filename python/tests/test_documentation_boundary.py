"""Regressions for escaped documentation links and private-repository references."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check-documentation.py"
SPEC = importlib.util.spec_from_file_location("documentation_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
documentation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(documentation)
POLICY = {"organization": "example", "publicRepositories": ["example/provider"]}


def check(tmp_path, text, target=None):
    source = tmp_path / "README.md"
    source.write_text(text)
    if target is not None:
        (tmp_path / "guide.md").write_text(target)
    return documentation.check_documentation(tmp_path, [source], POLICY)


def test_private_reference_in_fenced_example_is_rejected(tmp_path):
    errors = check(tmp_path, "```text\nhttps://github.com/example/internal-service/blob/main/runbook.md\n```\n")
    assert len(errors) == 1
    assert "unreviewed organization repository" in errors[0]


def test_public_identity_and_upstream_links_are_allowed(tmp_path):
    assert check(tmp_path, "https://github.com/example/provider\nhttps://github.com/kubernetes-sigs/cluster-api") == []


@pytest.mark.parametrize(
    ("text", "target", "expected"),
    [
        ("[old](removed.md)", None, "missing local target"),
        ("[section](guide.md#obsolete)", "# Current\n", "missing heading"),
        ("[outside](../runbook.md)", None, "link escapes repository"),
    ],
)
def test_broken_navigation_fails(tmp_path, text, target, expected):
    assert expected in check(tmp_path, text, target)[0]


def test_real_headings_duplicate_anchors_and_fenced_examples(tmp_path):
    text = "[first](guide.md#host-trust) [second](guide.md#host-trust-1)\n```md\n[example](not-a-file.md)\n```\n"
    assert check(tmp_path, text, "# Host trust\n# Host trust\n") == []


def test_encoded_target_and_anchor(tmp_path):
    (tmp_path / "My Guide.md").write_text("# SSH `host` trust\n")
    assert check(tmp_path, "[trust](My%20Guide.md#ssh-host-trust)") == []


def test_deleted_file_cannot_be_hidden_by_valid_public_link(tmp_path):
    errors = check(tmp_path, "[source](https://github.com/example/provider)\n[old](removed.md)")
    assert len(errors) == 1
    assert "missing local target" in errors[0]
