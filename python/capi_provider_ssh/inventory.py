"""UID-bound host allocation and cleanup state; claims survive failed operations."""

from __future__ import annotations

import copy

import kopf
import kubernetes

from capi_provider_ssh import API_GROUP, API_VERSION
from capi_provider_ssh.api_io import request
from capi_provider_ssh.contracts import get_object, persist_machine_status

CONNECTION_FIELDS = ("address", "port", "user", "sshKeyRef", "sshHostKeyRef")


def consumer_ref(name: str, namespace: str, uid: str) -> dict:
    if not uid:
        raise kopf.PermanentError("Machine UID is required to claim a host")
    return {"kind": "SSHMachine", "name": name, "namespace": namespace, "uid": uid}


def same_consumer(ref: dict | None, name: str, namespace: str, uid: str) -> bool:
    return bool(
        ref
        and uid
        and ref.get("uid") == uid
        and ref.get("kind") == "SSHMachine"
        and ref.get("name") == name
        and ref.get("namespace") == namespace
    )


def connection_spec(spec: dict) -> dict:
    return {
        "address": spec.get("address"),
        "port": spec.get("port", 22),
        "user": spec.get("user", "root"),
        "sshKeyRef": copy.deepcopy(spec.get("sshKeyRef", {})),
        "sshHostKeyRef": copy.deepcopy(spec.get("sshHostKeyRef", {})),
    }


def _host_patch(host: dict, namespace: str, body: dict, *, status: bool = False) -> dict:
    meta = host["metadata"]
    body["metadata"] = {"uid": meta["uid"], "resourceVersion": meta["resourceVersion"]}
    api = kubernetes.client.CustomObjectsApi()
    method = api.patch_namespaced_custom_object_status if status else api.patch_namespaced_custom_object
    return request(
        method,
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshhosts",
        name=meta["name"],
        body=body,
    )


def set_host_phase(binding: dict, name: str, namespace: str, uid: str, phase: str, reason: str = "") -> None:
    if not binding.get("hostRef"):
        return
    host_ns, host_name = binding["hostRef"].split("/", 1)
    host = get_object("sshhosts", host_ns, host_name)
    if host["metadata"]["uid"] != binding["hostUID"] or not same_consumer(
        host.get("spec", {}).get("consumerRef"),
        name,
        namespace,
        uid,
    ):
        raise kopf.TemporaryError("Host ownership changed; refusing lifecycle state mutation", delay=15)
    _host_patch(host, host_ns, {"status": {"phase": phase, "inUse": True, "cleanupReason": reason}}, status=True)


def release_host(binding: dict, name: str, namespace: str, uid: str) -> None:
    """Called only after proven cleanup or a never-started operation; clear the claim last."""
    if not binding.get("hostRef"):
        return
    host_ns, host_name = binding["hostRef"].split("/", 1)
    host = get_object("sshhosts", host_ns, host_name)
    if host["metadata"]["uid"] != binding["hostUID"]:
        raise kopf.TemporaryError("Host UID changed before release", delay=15)
    ref = host.get("spec", {}).get("consumerRef")
    if not ref:
        return  # Retry after the previous release was already committed.
    if not same_consumer(ref, name, namespace, uid):
        raise kopf.TemporaryError("Cannot release another Machine UID's host", delay=15)
    host = _host_patch(
        host, host_ns, {"status": {"phase": "Available", "inUse": False, "cleanupReason": ""}}, status=True
    )
    _host_patch(host, host_ns, {"spec": {"consumerRef": None}})


def recover_unstarted_claim(name: str, namespace: str, uid: str) -> dict:
    """Recover only an existing UID claim after a crash, never select another host."""
    hosts = request(
        kubernetes.client.CustomObjectsApi().list_namespaced_custom_object,
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshhosts",
    )["items"]
    own = [host for host in hosts if same_consumer(host.get("spec", {}).get("consumerRef"), name, namespace, uid)]
    if len(own) > 1:
        raise kopf.TemporaryError("Multiple UID claims require inventory recovery before deletion", delay=30)
    if not own:
        return {}
    host = own[0]
    return {
        **connection_spec(host["spec"]),
        "machineUID": uid,
        "hostUID": host["metadata"]["uid"],
        "hostRef": f"{namespace}/{host['metadata']['name']}",
    }


def _select_host(spec: dict, status: dict, name: str, namespace: str, uid: str) -> dict:
    hosts = request(
        kubernetes.client.CustomObjectsApi().list_namespaced_custom_object,
        group=API_GROUP,
        version=API_VERSION,
        namespace=namespace,
        plural="sshhosts",
    )["items"]
    own = [h for h in hosts if same_consumer(h.get("spec", {}).get("consumerRef"), name, namespace, uid)]
    if len(own) > 1:
        raise kopf.PermanentError("Multiple hosts claimed by this Machine UID; explicit inventory repair required")
    if own:
        return own[0]  # Recover a claim even if labels or health changed before binding persistence.
    if spec.get("hostRef") or spec.get("providerID") or status.get("initialization", {}).get("provisioned"):
        raise kopf.PermanentError(
            "Existing machine has no matching UID-bound host claim; automatic replacement is forbidden"
        )
    labels = spec.get("hostSelector", {}).get("matchLabels") or {}
    if not labels:
        raise kopf.PermanentError("hostSelector.matchLabels must not be empty")
    candidates = sorted(hosts, key=lambda h: (h.get("status", {}).get("ready") is not True, h["metadata"]["name"]))
    for host in candidates:
        meta, host_spec, host_status = host["metadata"], host.get("spec", {}), host.get("status", {})
        if meta.get("deletionTimestamp") or not all(meta.get("labels", {}).get(k) == v for k, v in labels.items()):
            continue
        if host_spec.get("consumerRef") or host_status.get("phase") not in {None, "Available"}:
            continue  # Orphaned claims require cleanup/quarantine, never automatic reassignment.
        if host_status.get("ready") is False:
            continue
        try:
            return _host_patch(host, namespace, {"spec": {"consumerRef": consumer_ref(name, namespace, uid)}})
        except kubernetes.client.ApiException as exc:
            if exc.status in {404, 409}:
                continue
            raise
    raise kopf.TemporaryError("No available SSHHost matches the selector", delay=30)


def bind_machine(spec: dict, status: dict, name: str, namespace: str, uid: str, patch) -> dict:
    """Persist an immutable target before bootstrap; never change an existing allocation."""
    if not uid:
        raise kopf.PermanentError("SSHMachine metadata.uid is required")
    binding = copy.deepcopy(status.get("allocation"))
    if binding:
        if binding.get("machineUID") != uid:
            raise kopf.PermanentError("Allocation belongs to a different Machine UID")
        for field in ("address", "port", "hostRef"):
            if spec.get(field) is not None and spec[field] != binding.get(field):
                raise kopf.PermanentError(f"Allocated {field} is immutable; create a replacement Machine")
        if spec.get("providerID") and spec["providerID"] != f"ssh://{binding['address']}":
            raise kopf.PermanentError("providerID does not match the allocated target")
        if binding.get("hostRef"):
            host_ns, host_name = binding["hostRef"].split("/", 1)
            host = get_object("sshhosts", host_ns, host_name)
            if host["metadata"]["uid"] != binding.get("hostUID") or not same_consumer(
                host.get("spec", {}).get("consumerRef"),
                name,
                namespace,
                uid,
            ):
                raise kopf.PermanentError("Allocated SSHHost identity/claim changed; replacement is forbidden")
            for field in ("address", "port"):
                if connection_spec(host["spec"])[field] != binding[field]:
                    raise kopf.PermanentError(f"SSHHost {field} changed after allocation")
            if host.get("status", {}).get("phase") in {"Quarantined", "Cleaning"}:
                raise kopf.TemporaryError("Allocated host awaits cleanup or quarantine recovery", delay=30)
            target = connection_spec(host["spec"])
        else:
            target = connection_spec(spec)
        # Secrets can rotate; address/port/host UID cannot.
        binding.update({k: target[k] for k in ("user", "sshKeyRef", "sshHostKeyRef")})
    elif spec.get("hostSelector") or spec.get("hostRef"):
        host = _select_host(spec, status, name, namespace, uid)
        if host.get("status", {}).get("phase") in {"Quarantined", "Cleaning"}:
            raise kopf.TemporaryError("Host claim is quarantined or cleaning", delay=30)
        binding = {
            **connection_spec(host["spec"]),
            "machineUID": uid,
            "hostUID": host["metadata"]["uid"],
            "hostRef": f"{namespace}/{host['metadata']['name']}",
        }
    else:
        if not spec.get("address"):
            raise kopf.PermanentError("Either address or hostSelector must be provided")
        binding = {**connection_spec(spec), "machineUID": uid}
        if spec.get("providerID") and spec["providerID"] != f"ssh://{binding['address']}":
            raise kopf.PermanentError("providerID does not match the target")
    if status.get("allocation") != binding:
        # Commit selected connection fields first. A crash here is recoverable
        # from the UID claim; a crash after status persistence must not leave
        # the default Machine port pointing at a different SSH endpoint.
        current = get_object("sshmachines", namespace, name)
        if current["metadata"].get("uid") != uid:
            raise kopf.TemporaryError("Machine identity changed during allocation", delay=15)
        selected = {field: binding[field] for field in CONNECTION_FIELDS}
        if binding.get("hostRef"):
            selected["hostRef"] = binding["hostRef"]
        request(
            kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object,
            group=API_GROUP,
            version=API_VERSION,
            namespace=namespace,
            plural="sshmachines",
            name=name,
            body={
                "metadata": {"uid": uid, "resourceVersion": current["metadata"]["resourceVersion"]},
                "spec": selected,
            },
        )
        persist_machine_status(namespace, name, uid, {"allocation": binding})
    patch.status["allocation"] = binding
    for field in CONNECTION_FIELDS:
        patch.spec[field] = binding[field]
    if binding.get("hostRef"):
        patch.spec["hostRef"] = binding["hostRef"]
        set_host_phase(binding, name, namespace, uid, "Claimed")
    return binding
