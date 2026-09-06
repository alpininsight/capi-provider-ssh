"""Local test harness: real CAPI/Kopf, SSH and kubeadm; explicit Kind context only."""

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import asyncssh
import kubernetes

SSH_GROUP = "infrastructure.alpininsight.ai"
CAPI_GROUP = "cluster.x-k8s.io"


def run(*args, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True, check=True, timeout=180).stdout


def eventually(description, check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(2)
    raise AssertionError(f"Timed out: {description}")


class Runtime:
    def __init__(self, kubeconfig, namespace):
        _, current = kubernetes.config.list_kube_config_contexts(config_file=kubeconfig)
        if not current["name"].startswith("kind-capi-ssh-"):
            raise ValueError("Lifecycle tests require an explicitly named kind-capi-ssh-* context")
        kubernetes.config.load_kube_config(config_file=kubeconfig)
        if urlparse(kubernetes.client.Configuration.get_default_copy().host).hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Lifecycle tests require a loopback Kind API endpoint")
        self.kubeconfig = kubeconfig
        self.namespace = namespace
        self.core = kubernetes.client.CoreV1Api()
        self.api = kubernetes.client.CustomObjectsApi()
        self.apps = kubernetes.client.AppsV1Api()
        self.targets = {}

    def create(self, group, plural, kind, name, spec, *, metadata=None):
        return self.api.create_namespaced_custom_object(
            group,
            "v1beta1",
            self.namespace,
            plural,
            {
                "apiVersion": f"{group}/v1beta1",
                "kind": kind,
                "metadata": {"name": name, "namespace": self.namespace, **(metadata or {})},
                "spec": spec,
            },
        )

    def get(self, group, plural, name):
        return self.api.get_namespaced_custom_object(group, "v1beta1", self.namespace, plural, name)

    def patch(self, group, plural, name, body):
        return self.api.patch_namespaced_custom_object(group, "v1beta1", self.namespace, plural, name, body)

    def secret(self, name, data):
        self.core.create_namespaced_secret(
            self.namespace,
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name},
                "stringData": data,
            },
        )

    def prepare_target(self, role):
        container = f"{self.namespace}-{role}"
        run(
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "--hostname",
            role,
            "--label",
            "capi-provider-ssh-test=true",
            "--privileged",
            "--cgroupns=private",
            "--network",
            "kind",
            "--tmpfs",
            "/run",
            "--tmpfs",
            "/tmp",
            "--volume",
            "/var",
            "--volume",
            "/lib/modules:/lib/modules:ro",
            os.environ.get("KIND_SSH_TARGET_IMAGE", "capi-ssh-kubeadm-target:p1"),
        )
        self.targets[role] = {"container": container}
        eventually(
            "target containerd",
            lambda: (
                run("docker", "exec", container, "sh", "-c", "systemctl is-active containerd || true").strip()
                == "active"
            ),
        )
        key = asyncssh.generate_private_key("ssh-ed25519")
        run(
            "docker",
            "exec",
            "-i",
            container,
            "sh",
            "-ceu",
            "install -d -m 0700 /root/.ssh; cat > /root/.ssh/authorized_keys; chmod 0600 /root/.ssh/authorized_keys; "
            "ssh-keygen -A >/dev/null; install -d -m 0755 /run/sshd; systemctl reset-failed ssh; systemctl restart ssh",
            input=key.export_public_key().decode(),
        )
        address = run(
            "docker", "inspect", container, "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"
        ).strip()
        # Trust originates from the isolated Docker console, never from ssh-keyscan/TOFU.
        host_key = run("docker", "exec", container, "cat", "/etc/ssh/ssh_host_ed25519_key.pub").strip()
        known_hosts = f"{address} {host_key}\n"
        self.secret(role + "-key", {"value": key.export_private_key().decode()})
        self.secret(role + "-trust", {"known_hosts": known_hosts})
        self.targets[role].update(address=address, key=key.export_private_key().decode(), known_hosts=known_hosts)
        self.create(
            SSH_GROUP,
            "sshhosts",
            "SSHHost",
            role,
            {
                "address": address,
                "port": 22,
                "user": "root",
                "sshKeyRef": {"name": role + "-key"},
                "sshHostKeyRef": {"name": role + "-trust"},
            },
            metadata={"labels": {"test-role": "control-plane" if role.startswith("cp") else "worker"}},
        )
        return address

    def start_control_plane(self):
        address = self.targets["cp-0"]["address"]
        self.create(
            SSH_GROUP,
            "sshclusters",
            "SSHCluster",
            "workload",
            {
                "controlPlaneEndpoint": {"host": address, "port": 6443},
            },
        )
        self.create(
            SSH_GROUP,
            "sshmachinetemplates",
            "SSHMachineTemplate",
            "control-plane",
            {
                "template": {"spec": {"hostSelector": {"matchLabels": {"test-role": "control-plane"}}}},
            },
        )
        self.create(
            CAPI_GROUP,
            "clusters",
            "Cluster",
            "workload",
            {
                "controlPlaneEndpoint": {"host": address, "port": 6443},
                "clusterNetwork": {
                    "pods": {"cidrBlocks": ["10.244.0.0/16"]},
                    "services": {"cidrBlocks": ["10.96.0.0/12"]},
                },
                "infrastructureRef": {"apiVersion": f"{SSH_GROUP}/v1beta1", "kind": "SSHCluster", "name": "workload"},
                "controlPlaneRef": {
                    "apiVersion": "controlplane.cluster.x-k8s.io/v1beta1",
                    "kind": "KubeadmControlPlane",
                    "name": "workload",
                },
            },
        )
        self.create(
            "controlplane.cluster.x-k8s.io",
            "kubeadmcontrolplanes",
            "KubeadmControlPlane",
            "workload",
            {
                "replicas": 1,
                "version": "v1.34.11",
                "machineTemplate": {
                    "infrastructureRef": {
                        "apiVersion": f"{SSH_GROUP}/v1beta1",
                        "kind": "SSHMachineTemplate",
                        "name": "control-plane",
                    }
                },
                "kubeadmConfigSpec": {
                    "clusterConfiguration": {
                        "apiServer": {"certSANs": [address]},
                        "controllerManager": {"extraArgs": {"node-cidr-mask-size": "24"}},
                    },
                    "initConfiguration": {
                        "nodeRegistration": {
                            "kubeletExtraArgs": {"eviction-hard": "memory.available<50Mi", "fail-swap-on": "false"}
                        }
                    },
                    "joinConfiguration": {
                        "nodeRegistration": {
                            "kubeletExtraArgs": {"eviction-hard": "memory.available<50Mi", "fail-swap-on": "false"}
                        }
                    },
                },
            },
        )

    def machines(self):
        return self.api.list_namespaced_custom_object(SSH_GROUP, "v1beta1", self.namespace, "sshmachines")["items"]

    def container(self, role):
        return f"{self.namespace}-{role}"

    def install_cni(self):
        items = []
        for resource in (
            "serviceaccount/kindnet",
            "clusterrole/kindnet",
            "clusterrolebinding/kindnet",
            "daemonset/kindnet",
        ):
            obj = json.loads(
                run("kubectl", "--kubeconfig", self.kubeconfig, "-n", "kube-system", "get", resource, "-o", "json")
            )
            for key in ("resourceVersion", "uid", "creationTimestamp", "managedFields", "annotations"):
                obj["metadata"].pop(key, None)
            obj.pop("status", None)
            if obj["kind"] == "DaemonSet":
                for env in obj["spec"]["template"]["spec"]["containers"][0]["env"]:
                    if env["name"] == "CONTROL_PLANE_ENDPOINT":
                        env["value"] = self.get(SSH_GROUP, "sshhosts", "cp-0")["spec"]["address"] + ":6443"
            items.append(obj)
        run(
            "docker",
            "exec",
            "-i",
            self.container("cp-0"),
            "kubectl",
            "--kubeconfig",
            "/etc/kubernetes/admin.conf",
            "apply",
            "-f",
            "-",
            input=json.dumps({"apiVersion": "v1", "kind": "List", "items": items}),
        )

    def worker_bootstrap_template(self, name, *, delay=False):
        spec = {"joinConfiguration": {"nodeRegistration": {"kubeletExtraArgs": {"fail-swap-on": "false"}}}}
        if delay:
            spec["preKubeadmCommands"] = [
                "trap '' HUP",
                "printf 'attempt\\n' >> /var/lib/capi-provider-ssh/attempts",
                "sleep 25",
            ]
        self.create(
            "bootstrap.cluster.x-k8s.io",
            "kubeadmconfigtemplates",
            "KubeadmConfigTemplate",
            name,
            {"template": {"spec": spec}},
        )

    def start_workers(self):
        self.create(
            SSH_GROUP,
            "sshmachinetemplates",
            "SSHMachineTemplate",
            "workers",
            {
                "template": {"spec": {"hostSelector": {"matchLabels": {"test-role": "worker"}}}},
            },
        )
        self.worker_bootstrap_template("workers")
        labels = {"cluster.x-k8s.io/cluster-name": "workload", "test-pool": "workers"}
        self.create(
            CAPI_GROUP,
            "machinedeployments",
            "MachineDeployment",
            "workers",
            {
                "clusterName": "workload",
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "clusterName": "workload",
                        "version": "v1.34.11",
                        "bootstrap": {
                            "configRef": {
                                "apiVersion": "bootstrap.cluster.x-k8s.io/v1beta1",
                                "kind": "KubeadmConfigTemplate",
                                "name": "workers",
                            }
                        },
                        "infrastructureRef": {
                            "apiVersion": f"{SSH_GROUP}/v1beta1",
                            "kind": "SSHMachineTemplate",
                            "name": "workers",
                        },
                    },
                },
            },
        )

    def ready_nodes(self, count):
        def check():
            nodes = json.loads(
                run(
                    "docker",
                    "exec",
                    self.container("cp-0"),
                    "kubectl",
                    "--kubeconfig",
                    "/etc/kubernetes/admin.conf",
                    "get",
                    "nodes",
                    "-o",
                    "json",
                )
            )["items"]
            return len(nodes) == count and all(
                any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"]) for n in nodes
            )

        return eventually(f"{count} Ready workload Nodes", check, timeout=600)

    def reuse_worker_with_failover(self):
        self.worker_bootstrap_template("workers-ha", delay=True)
        self.patch(
            CAPI_GROUP,
            "machinedeployments",
            "workers",
            {
                "spec": {
                    "replicas": 1,
                    "template": {"spec": {"bootstrap": {"configRef": {"name": "workers-ha"}}}},
                }
            },
        )
        eventually(
            "remote bootstrap entered",
            lambda: (
                run(
                    "docker",
                    "exec",
                    self.container("worker-0"),
                    "sh",
                    "-c",
                    "test -f /var/lib/capi-provider-ssh/attempts && "
                    "wc -l < /var/lib/capi-provider-ssh/attempts || true",
                ).strip()
                == "1"
            ),
        )
        peers = self.api.get_cluster_custom_object("kopf.dev", "v1", "clusterkopfpeerings", "capi-provider-ssh")[
            "status"
        ]
        identity = max(peers, key=lambda name: peers[name]["priority"])
        pods = self.core.list_namespaced_pod(
            "capi-provider-ssh-system", label_selector="app.kubernetes.io/name=capi-provider-ssh"
        ).items
        leader = next(p for p in pods if p.metadata.name in identity)
        started = time.monotonic()
        self.core.delete_namespaced_pod(leader.metadata.name, "capi-provider-ssh-system", grace_period_seconds=0)
        self.wait_provisioned(4)
        self.ready_nodes(4)
        attempts = run(
            "docker", "exec", self.container("worker-0"), "cat", "/var/lib/capi-provider-ssh/attempts"
        ).splitlines()
        assert attempts == ["attempt"], "A takeover replayed the successfully completed remote bootstrap"
        return {
            "terminatedPod": leader.metadata.name,
            "terminatedPodUID": leader.metadata.uid,
            "bootstrapAttempts": len(attempts),
            "recoverySeconds": round(time.monotonic() - started, 1),
        }

    def wait_provisioned(self, count):
        return eventually(
            f"{count} real kubeadm bootstraps",
            lambda: (
                len([m for m in self.machines() if m.get("status", {}).get("initialization", {}).get("provisioned")])
                >= count
            ),
            timeout=600,
        )

    def snapshot(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Public diagnostic state only: no Secret payloads or kubeconfigs in test artifacts.
        for group, plural in (
            (SSH_GROUP, "sshmachines"),
            (SSH_GROUP, "sshhosts"),
            (CAPI_GROUP, "machines"),
            (CAPI_GROUP, "clusters"),
        ):
            result = self.api.list_namespaced_custom_object(group, "v1beta1", self.namespace, plural)
            (directory / f"{plural}.json").write_text(json.dumps(result, indent=2))
