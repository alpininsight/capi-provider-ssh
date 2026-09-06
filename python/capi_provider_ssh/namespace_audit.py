"""Read-only detection of abandoned test namespaces; never remove finalizers."""

import datetime
import json

import kubernetes

TEST_LABEL = "capi-provider-ssh-test"
MIN_AGE = datetime.timedelta(hours=1)


def is_stuck_test(namespace: dict, now: datetime.datetime) -> bool:
    meta = namespace.get("metadata", {})
    if not meta.get("name", "").startswith("test-capi-ssh-") or meta.get("labels", {}).get(TEST_LABEL) != "true":
        return False
    if namespace.get("status", {}).get("phase") != "Terminating":
        return False
    deleted = meta.get("deletionTimestamp")
    if not deleted:
        return False
    try:
        timestamp = datetime.datetime.fromisoformat(deleted.replace("Z", "+00:00"))
        return timestamp.tzinfo is not None and now - timestamp >= MIN_AGE
    except (ValueError, TypeError):
        return False


def audit(core, custom, *, now=None) -> list[dict]:
    now = now or datetime.datetime.now(datetime.UTC)
    namespaces = core.list_namespace(label_selector=f"{TEST_LABEL}=true", _request_timeout=(5, 15))
    findings = []
    for namespace in namespaces.items:
        obj = kubernetes.client.ApiClient().sanitize_for_serialization(namespace)
        if not is_stuck_test(obj, now):
            continue
        name = obj["metadata"]["name"]
        resources = []
        for group, plural in (("cluster.x-k8s.io", "machines"), ("infrastructure.alpininsight.ai", "sshmachines")):
            for item in custom.list_namespaced_custom_object(
                group=group, version="v1beta1", namespace=name, plural=plural, _request_timeout=(5, 15)
            )["items"]:
                resources.append(
                    {
                        "kind": item["kind"],
                        "name": item["metadata"]["name"],
                        "uid": item["metadata"]["uid"],
                        "finalizers": item["metadata"].get("finalizers", []),
                        "cleanup": item.get("status", {}).get("cleanup", {}).get("phase"),
                    }
                )
        findings.append(
            {
                "namespace": name,
                "deletionTimestamp": obj["metadata"]["deletionTimestamp"],
                "resources": resources,
                "action": "Investigate cleanup; finalizers and claims preserved",
            }
        )
    return findings


def main() -> int:
    kubernetes.config.load_incluster_config()
    findings = audit(kubernetes.client.CoreV1Api(), kubernetes.client.CustomObjectsApi())
    print(json.dumps({"stuckTestNamespaces": findings}, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
