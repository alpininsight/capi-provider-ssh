"""Install pinned test prerequisites; invoked only by the disposable Kind runner."""

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

import yaml

from tests.kind.runtime import Runtime, run


def main():
    kubeconfig = os.environ["KIND_TEST_KUBECONFIG"]
    Runtime(kubeconfig, "unused")  # Verify explicit local context before any apply.
    root = Path(__file__).resolve().parents[3]
    temporary = Path(os.environ["KIND_TEST_ARTIFACTS"])
    temporary.mkdir(parents=True, exist_ok=True)
    files = {}
    for asset in json.loads(Path(__file__).with_name("upstream.json").read_text()):
        with urllib.request.urlopen(asset["url"], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise RuntimeError(f"Upstream asset hash mismatch: {asset['name']}")
        rendered = re.sub(r"\$\{[^}:]+:=([^}]+)\}", lambda match: match[1], data.decode())
        docs = list(yaml.safe_load_all(rendered))
        for obj in docs:
            if obj and obj.get("aggregationRule"):
                obj.pop("rules", None)
            if obj and obj["kind"] == "Deployment" and asset["name"] != "cert-manager.yaml":
                obj["spec"]["replicas"] = 2
        file = temporary / asset["name"]
        file.write_text(yaml.safe_dump_all(docs))
        files[asset["name"]] = str(file)

    def kubectl(*args):
        return run("kubectl", "--kubeconfig", kubeconfig, *args)

    kubectl("apply", "--server-side", "-f", files.pop("cert-manager.yaml"))
    kubectl("-n", "cert-manager", "wait", "--for=condition=Available", "deployment", "--all", "--timeout=180s")
    for file in files.values():
        kubectl("apply", "--server-side", "-f", file)
    for namespace in ("capi-system", "capi-kubeadm-bootstrap-system", "capi-kubeadm-control-plane-system"):
        kubectl("-n", namespace, "wait", "--for=condition=Available", "deployment", "--all", "--timeout=180s")
    kubectl("apply", "-k", str(root / "shared/crds"))
    deploy = root / "python/deploy"
    kubectl("apply", "-f", str(deploy / "namespace.yaml"), "-f", str(deploy / "rbac.yaml"))
    peer_crd, peer = list(yaml.safe_load_all((deploy / "peering.yaml").read_text()))
    for name, obj in (("peer-crd", peer_crd), ("peer", peer)):
        file = temporary / f"{name}.yaml"
        file.write_text(yaml.safe_dump(obj))
        kubectl("apply", "-f", str(file))
        if name == "peer-crd":
            kubectl("wait", "--for=condition=Established", "crd/clusterkopfpeerings.kopf.dev", "--timeout=60s")
    obj = yaml.safe_load((deploy / "deployment.yaml").read_text())
    container = obj["spec"]["template"]["spec"]["containers"][0]
    container["image"] = "capi-provider-ssh:kind-test"
    container["imagePullPolicy"] = "Never"
    for env in container["env"]:
        if env["name"] == "RECONCILE_INTERVAL":
            env["value"] = "3"
    file = temporary / "test-provider.yaml"
    file.write_text(yaml.safe_dump(obj))
    kubectl("apply", "-f", str(file), "-f", str(deploy / "pdb.yaml"))
    kubectl(
        "-n",
        "capi-provider-ssh-system",
        "rollout",
        "status",
        "deployment/capi-provider-ssh-controller",
        "--timeout=180s",
    )


if __name__ == "__main__":
    main()
