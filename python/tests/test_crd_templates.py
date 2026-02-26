"""Tests for CRD template manifests."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CRD_DIR = REPO_ROOT / "shared" / "crds"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_sshclustertemplate_crd_schema_contract() -> None:
    crd = _load_yaml(CRD_DIR / "sshclustertemplate.yaml")

    assert crd["kind"] == "CustomResourceDefinition"
    assert crd["metadata"]["name"] == "sshclustertemplates.infrastructure.alpininsight.ai"
    assert crd["spec"]["names"]["kind"] == "SSHClusterTemplate"
    assert crd["spec"]["names"]["plural"] == "sshclustertemplates"

    schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    spec_schema = schema["properties"]["spec"]
    assert "template" in spec_schema["required"]

    template_schema = spec_schema["properties"]["template"]
    assert "spec" in template_schema["required"]
    template_spec = template_schema["properties"]["spec"]
    assert "controlPlaneEndpoint" in template_spec["required"]

    endpoint = template_spec["properties"]["controlPlaneEndpoint"]
    assert sorted(endpoint["required"]) == ["host", "port"]


def test_sshclustertemplate_template_spec_is_immutable() -> None:
    crd = _load_yaml(CRD_DIR / "sshclustertemplate.yaml")
    spec_schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
    validations = spec_schema.get("x-kubernetes-validations", [])

    assert any(v.get("rule") == "self.template.spec == oldSelf.template.spec" for v in validations), (
        "SSHClusterTemplate must enforce spec.template.spec immutability."
    )


def test_crd_kustomization_includes_sshclustertemplate() -> None:
    kustomization = _load_yaml(CRD_DIR / "kustomization.yaml")
    resources = kustomization.get("resources", [])

    assert "sshclustertemplate.yaml" in resources


def test_sshmachine_crd_bootstrap_check_strategy_enum() -> None:
    crd = _load_yaml(CRD_DIR / "sshmachine.yaml")
    spec_properties = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    strategy = spec_properties["bootstrapCheckStrategy"]

    assert strategy["type"] == "string"
    assert strategy["default"] == "ssh"
    assert sorted(strategy["enum"]) == ["none", "ssh"]


def test_sshmachinetemplate_crd_bootstrap_check_strategy_enum() -> None:
    crd = _load_yaml(CRD_DIR / "sshmachinetemplate.yaml")
    template_spec_properties = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"][
        "properties"
    ]["template"]["properties"]["spec"]["properties"]
    strategy = template_spec_properties["bootstrapCheckStrategy"]

    assert strategy["type"] == "string"
    assert strategy["default"] == "ssh"
    assert sorted(strategy["enum"]) == ["none", "ssh"]
