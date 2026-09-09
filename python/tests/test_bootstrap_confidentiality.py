"""Secret-backed errors must be safe at the actual reconciliation boundary."""

import json
import logging
import traceback

import kopf
import pytest
import yaml

from capi_provider_ssh.controllers import sshmachine as controller
from tests import test_lifecycle_contract as lifecycle_tests

api = lifecycle_tests.api
ssh = lifecycle_tests.ssh
reconcile = lifecycle_tests.reconcile

MARKER = "SYNTHETIC_BOOTSTRAP_SECRET"


def cloud_file(**fields):
    return "#cloud-config\n" + yaml.safe_dump(
        {"write_files": [{"path": "/etc/kubernetes/kubeadm.yaml", **fields}], "runcmd": []}
    )


@pytest.mark.parametrize(
    "payload",
    [
        f"#cloud-config\nwrite_files:\n  - content: {MARKER}: invalid\n",
        f"#cloud-config\nvalue: !{MARKER} data\n",
        f"#cloud-config\nvalue: {MARKER}\0\n",
        cloud_file(content="{}", encoding=MARKER),
        cloud_file(content=f"{MARKER}: invalid", encoding="base64"),
        cloud_file(content=yaml.safe_dump({"apiVersion": MARKER, "kind": "InitConfiguration"})),
    ],
    ids=["yaml-syntax", "yaml-tag", "yaml-reader", "encoding-name", "base64", "kubeadm-version"],
)
async def test_secret_payload_is_absent_from_status_exception_and_logs(api, ssh, caplog, payload):
    machine = api.machine()
    api.secret("bootstrap", payload)
    with pytest.raises(kopf.PermanentError) as caught:
        await reconcile(api, machine)
    error = caught.value
    # Kopf logs and persists the raised error. Exercise normal traceback
    # formatting as well as status/conditions, including exception chaining.
    logging.getLogger("test.handler").error("Handler failed", exc_info=(type(error), error, error.__traceback__))
    public = json.dumps(api.current(machine)["status"]) + str(error) + "".join(traceback.format_exception(error))
    assert MARKER not in public
    assert MARKER not in caplog.text
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "bootstrap" not in ssh.events


def test_yaml_error_retains_position_without_payload():
    with pytest.raises(kopf.PermanentError, match=r"line 3, column \d+"):
        controller._parse_cloud_config(f"#cloud-config\nwrite_files:\n  - content: {MARKER}: invalid\n")


def test_base64_cloud_file_accepts_wrapped_content():
    assert controller._decode_cloud_write_file_content({"content": "aGVs\nbG8=\n", "encoding": "base64"}, 0) == "hello"
