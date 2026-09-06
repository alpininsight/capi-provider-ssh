"""Kopf entrypoint for capi-provider-ssh."""

import hashlib
import logging
import os
import uuid

import kopf
import kubernetes

# Import controllers to register their handlers with kopf
import capi_provider_ssh.controllers.sshcluster  # noqa: F401
import capi_provider_ssh.controllers.sshhost  # noqa: F401
import capi_provider_ssh.controllers.sshmachine  # noqa: F401

logger = logging.getLogger(__name__)

# Runtime configuration (environment variables)
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "30"))
SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "300"))
RECONCILE_INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_kwargs):
    """Configure kopf operator settings."""
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage()
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270
    settings.watching.client_timeout = 300
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        kubernetes.config.load_incluster_config()
    elif os.environ.get("KUBECONFIG"):
        kubernetes.config.load_kube_config(config_file=os.environ["KUBECONFIG"])
    else:
        raise RuntimeError("Set KUBECONFIG explicitly for local execution, or run with in-cluster credentials")
    if os.environ.get("SSH_PROVIDER_HA", "true").lower() == "true":
        identity = os.environ.get("POD_UID") or str(uuid.uuid4())
        settings.peering.name = "capi-provider-ssh"
        settings.peering.mandatory = True
        settings.peering.standalone = False
        settings.peering.priority = int(hashlib.sha256(identity.encode()).hexdigest()[:15], 16)
        settings.peering.lifetime = 30
