"""Stateful API model: UID/resourceVersion CAS and real status-subresource semantics.

Used for deterministic failure schedules; Kind tests separately verify the real API.
"""

import base64
import copy
import threading
import uuid
from types import SimpleNamespace

import kubernetes

from capi_provider_ssh import API_GROUP


def merge(target, patch):
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            merge(target.setdefault(key, {}), value)
        else:
            target[key] = copy.deepcopy(value)


class ObjectStore:
    def __init__(self):
        self.objects = {}
        self.leases = {}
        self.secrets = {}
        self.calls = []
        self.lock = threading.RLock()
        self.status_failure = False
        self.claim_conflicts = 0

    def add(self, plural, name, spec=None, status=None, *, namespace="test", group=API_GROUP, uid=None, meta=None):
        obj = {
            "apiVersion": group + "/v1beta1",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "uid": uid or str(uuid.uuid4()),
                "resourceVersion": "1",
                **(meta or {}),
            },
            "spec": copy.deepcopy(spec or {}),
            "status": copy.deepcopy(status or {}),
        }
        self.objects[group, plural, namespace, name] = obj
        return copy.deepcopy(obj)

    def secret(self, name, value, key="value", namespace="test"):
        self.secrets[namespace, name] = SimpleNamespace(data={key: base64.b64encode(value.encode()).decode()})

    def read_namespaced_secret(self, name, namespace):
        return self.secrets[namespace, name]

    def get_namespaced_custom_object(self, group, version, namespace, plural, name, **kwargs):
        with self.lock:
            try:
                return copy.deepcopy(self.objects[group, plural, namespace, name])
            except KeyError as exc:
                raise kubernetes.client.ApiException(status=404) from exc

    def list_namespaced_custom_object(self, group, version, namespace, plural, **kwargs):
        with self.lock:
            return {
                "items": [
                    copy.deepcopy(o)
                    for (g, p, ns, _), o in self.objects.items()
                    if (g, p, ns) == (group, plural, namespace)
                ]
            }

    def _patch(self, group, version, namespace, plural, name, body, *, status=False, **kwargs):
        with self.lock:
            obj = self.objects[group, plural, namespace, name]
            supplied = body.get("metadata", {})
            for field in ("uid", "resourceVersion"):
                if supplied.get(field) is not None and supplied[field] != obj["metadata"][field]:
                    raise kubernetes.client.ApiException(status=409)
            if status and self.status_failure:
                raise kubernetes.client.ApiException(status=500)
            if plural == "sshhosts" and "consumerRef" in body.get("spec", {}) and self.claim_conflicts:
                self.claim_conflicts -= 1
                raise kubernetes.client.ApiException(status=409)
            self.calls.append(("status" if status else "patch", plural, name, copy.deepcopy(body)))
            if status:
                merge(obj.setdefault("status", {}), body.get("status", {}))
            else:
                merge(obj, {k: v for k, v in body.items() if k != "status"})
            obj["metadata"]["resourceVersion"] = str(int(obj["metadata"]["resourceVersion"]) + 1)
            return copy.deepcopy(obj)

    def patch_namespaced_custom_object(self, **kwargs):
        return self._patch(**kwargs)

    def patch_namespaced_custom_object_status(self, **kwargs):
        return self._patch(**kwargs, status=True)

    def read_namespaced_lease(self, name, namespace, **kwargs):
        with self.lock:
            if (namespace, name) not in self.leases:
                raise kubernetes.client.ApiException(status=404)
            return copy.deepcopy(self.leases[namespace, name])

    def create_namespaced_lease(self, namespace, body, **kwargs):
        with self.lock:
            key = namespace, body.metadata.name
            if key in self.leases:
                raise kubernetes.client.ApiException(status=409)
            body = copy.deepcopy(body)
            body.metadata.resource_version = "1"
            self.leases[key] = body
            return copy.deepcopy(body)

    def replace_namespaced_lease(self, name, namespace, body, **kwargs):
        with self.lock:
            current = self.leases[namespace, name]
            if body.metadata.resource_version != current.metadata.resource_version:
                raise kubernetes.client.ApiException(status=409)
            body = copy.deepcopy(body)
            body.metadata.resource_version = str(int(current.metadata.resource_version) + 1)
            self.leases[namespace, name] = body
            return copy.deepcopy(body)

    def machine(self, name="machine-a", *, spec=None, namespace="test"):
        self.add("clusters", "cluster-a", group="cluster.x-k8s.io", namespace=namespace)
        capi = self.add(
            "machines",
            name,
            {"clusterName": "cluster-a", "bootstrap": {"dataSecretName": "bootstrap"}},
            group="cluster.x-k8s.io",
            namespace=namespace,
        )
        self.secret("key", "test-private-key", namespace=namespace)
        self.secret("trust", "test-known-hosts", key="known_hosts", namespace=namespace)
        self.secret("bootstrap", "#!/bin/sh\necho test bootstrap\n", namespace=namespace)
        return self.add(
            "sshmachines",
            name,
            spec=spec
            or {
                "address": "192.0.2.10",
                "port": 2222,
                "sshKeyRef": {"name": "key"},
                "sshHostKeyRef": {"name": "trust"},
            },
            namespace=namespace,
            meta={
                "ownerReferences": [
                    {"apiVersion": capi["apiVersion"], "kind": "Machine", "name": name, "uid": capi["metadata"]["uid"]}
                ]
            },
        )

    def current(self, obj, plural="sshmachines"):
        return self.get_namespaced_custom_object(
            API_GROUP, "v1beta1", obj["metadata"]["namespace"], plural, obj["metadata"]["name"]
        )
