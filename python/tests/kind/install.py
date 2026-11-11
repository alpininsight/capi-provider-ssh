"""Install pinned test prerequisites; invoked only by the disposable Kind runner."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import yaml

from tests.kind.runtime import Runtime, run

DOWNLOAD_BUDGET_SECONDS = 60
MAX_ASSET_BYTES = 64 * 1024 * 1024


def download_asset(asset):
    """Retry public, pinned GETs within one process budget; never log response data."""
    url = urlsplit(asset["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise RuntimeError(f"Pinned asset requires an uncredentialed HTTPS URL: {asset['name']}")
    with TemporaryDirectory(prefix="capi-kind-asset-") as temporary:
        target = Path(temporary) / "asset"
        # curl already supplies the Kind binary in this lane. A subprocess
        # budget also bounds slow bodies and Retry-After, not just urlopen's
        # individual socket operations. Output files are truncated on retries.
        command = [
            "curl",
            "--disable",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--retry",
            "2",
            "--retry-delay",
            "1",
            "--retry-max-time",
            str(DOWNLOAD_BUDGET_SECONDS),
            "--connect-timeout",
            "10",
            "--max-time",
            "20",
            "--max-filesize",
            str(MAX_ASSET_BYTES),
            "--output",
            str(target),
            "--write-out",
            "%{http_code}",
            asset["url"],
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=DOWNLOAD_BUDGET_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Pinned asset download exceeded its time budget: {asset['name']}") from None
        except OSError:
            raise RuntimeError(f"Pinned asset downloader is unavailable: {asset['name']}") from None
        if result.returncode or result.stdout != b"200":
            raise RuntimeError(f"Pinned asset download failed: {asset['name']} (curl exit {result.returncode})")
        if target.stat().st_size > MAX_ASSET_BYTES:
            raise RuntimeError(f"Pinned asset exceeds the size budget: {asset['name']}")
        data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise RuntimeError(f"Upstream asset hash mismatch: {asset['name']}")
    return data


def main():
    kubeconfig = os.environ["KIND_TEST_KUBECONFIG"]
    Runtime(kubeconfig, "unused")  # Verify explicit local context before any apply.
    root = Path(__file__).resolve().parents[3]
    temporary = Path(os.environ["KIND_TEST_ARTIFACTS"])
    temporary.mkdir(parents=True, exist_ok=True)
    files = {}
    for asset in json.loads(Path(__file__).with_name("upstream.json").read_text()):
        data = download_asset(asset)
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
