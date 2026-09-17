"""Allowlisted lifecycle evidence; never export API/log free text or object specs."""

import re

KINDS = {"SSHMachine", "Machine", "MachineSet", "MachineDeployment", "Cluster", "KubeadmControlPlane", "Pod"}
CONDITION_TYPES = {
    "Ready",
    "Paused",
    "InfrastructureReady",
    "BootstrapExecSucceeded",
    "MachinesCreated",
    "MachinesReady",
    "Available",
    "UpToDate",
    "ScalingUp",
    "ScalingDown",
    "Remediating",
    "Deleting",
}
REASONS = {
    "Ready",
    "NotReady",
    "NotPaused",
    "Paused",
    "WaitingForMachineOwner",
    "BootstrapNotStarted",
    "InfrastructureTemplateCloningFailed",
    "BootstrapTemplateCloningFailed",
    "InternalError",
    "SuccessfulCreate",
    "FailedCreate",
    "SuccessfulDelete",
    "FailedDelete",
    "SuccessfulAdopt",
    "FailedAdopt",
}
MANAGERS = {"capi-machineset", "capi-machineset-metadata", "capi-machinedeployment", "capi-machine", "manager", "kopf"}
ERROR_PHRASES = {
    "InfraMachineCreateFailed": "failed to create InfraMachine",
    "InfrastructureCloneFailed": "failed to clone infrastructure machine",
    "ManagedFieldsCleanupFailed": "failed to remove managedFields for labels and annotations",
    "OptimisticLockConflict": "the object has been modified",
}


def reference(value):
    """Only public Kubernetes identities; Secret/ConfigMap references are excluded."""
    if value.get("kind") not in KINDS:
        return {}
    result = {"kind": value["kind"]}
    for field in ("name", "namespace"):
        text = value.get(field)
        if isinstance(text, str) and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", text):
            result[field] = text
    uid = value.get("uid")
    if isinstance(uid, str) and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", uid):
        result["uid"] = uid
    return result


def error_classes(text):
    return [code for code, phrase in ERROR_PHRASES.items() if isinstance(text, str) and phrase in text]


def conditions(values):
    return [
        {
            "type": item.get("type") if item.get("type") in CONDITION_TYPES else "Other",
            "status": item.get("status") if item.get("status") in {"True", "False", "Unknown"} else "Other",
            "reason": item.get("reason") if item.get("reason") in REASONS else "Other",
            **(
                {"observedGeneration": item["observedGeneration"]}
                if type(item.get("observedGeneration")) is int
                else {}
            ),
            "errorClasses": error_classes(item.get("message", "")),
        }
        for item in values
    ]


def resource(value):
    metadata = value.get("metadata", {})
    result = reference({**metadata, "kind": value.get("kind")})
    if not result:
        return {}
    if type(metadata.get("generation")) is int:
        result["generation"] = metadata["generation"]
    rv = metadata.get("resourceVersion")
    if isinstance(rv, str) and re.fullmatch(r"[0-9]{1,32}", rv):
        result["resourceVersion"] = rv
    result["deleting"] = bool(metadata.get("deletionTimestamp"))
    result["ownerReferences"] = [ref for owner in metadata.get("ownerReferences", []) if (ref := reference(owner))]
    result["managedFields"] = [
        {
            "manager": item.get("manager") if item.get("manager") in MANAGERS else "Other",
            "operation": item.get("operation") if item.get("operation") in {"Apply", "Update"} else "Other",
            "subresource": "status" if item.get("subresource") == "status" else "Other",
        }
        for item in metadata.get("managedFields", [])
    ]
    if value.get("kind") == "Machine":
        result["infrastructureRef"] = reference(value.get("spec", {}).get("infrastructureRef", {}))
    status = value.get("status", {})
    result["status"] = {
        field: status[field]
        for field in ("observedGeneration", "replicas", "readyReplicas", "availableReplicas", "updatedReplicas")
        if type(status.get(field)) is int
    }
    for field in ("ready", "infrastructureReady"):
        if type(status.get(field)) is bool:
            result["status"][field] = status[field]
    provisioned = status.get("initialization", {}).get("provisioned")
    if type(provisioned) is bool:
        result["status"]["provisioned"] = provisioned
    result["status"]["conditions"] = conditions(status.get("conditions", []))
    result["status"]["v1beta2Conditions"] = conditions(status.get("v1beta2", {}).get("conditions", []))
    return result


def event(value, namespace):
    ref = reference(value.get("involvedObject", {}))
    if not ref or ref.get("namespace") != namespace:
        return None
    return {
        "object": ref,
        "type": value.get("type") if value.get("type") in {"Normal", "Warning"} else "Other",
        "reason": value.get("reason") if value.get("reason") in REASONS else "Other",
        "count": value.get("count") if type(value.get("count")) is int else None,
        "errorClasses": error_classes(value.get("message", "")),
    }


def controller_errors(text, objects):
    """Classify bounded CAPI klog observations; unknown formats/errors stay unexported."""
    matches = {}
    for line in text.splitlines():
        codes = error_classes(line)
        if not codes:
            continue
        for item in objects:
            ref = reference(item)
            if not ref.get("namespace") or not ref.get("name"):
                continue
            # Match CAPI's structured klog object key, not arbitrary name substrings.
            if f'{ref["kind"]}="{ref["namespace"]}/{ref["name"]}"' not in line:
                continue
            for code in codes:
                key = (ref["kind"], ref["namespace"], ref["name"], code)
                if key not in matches:
                    matches[key] = {"objectAtSnapshot": ref, "errorClass": code, "count": 0}
                matches[key]["count"] += 1
    return list(matches.values())
