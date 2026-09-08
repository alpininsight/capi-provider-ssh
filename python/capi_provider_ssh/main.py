"""Kopf entrypoint for capi-provider-ssh."""

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime

import kopf

# Import controllers to register their handlers with kopf
import capi_provider_ssh.controllers.sshcluster  # noqa: F401
import capi_provider_ssh.controllers.sshhost  # noqa: F401
import capi_provider_ssh.controllers.sshmachine  # noqa: F401
from capi_provider_ssh.readiness import PEERING_LIFETIME, PEERING_NAME, load_api_config

logger = logging.getLogger(__name__)

# Runtime configuration (environment variables)
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "30"))
SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "300"))
RECONCILE_INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))
_runtime = {"configured": False}


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_kwargs):
    """Configure kopf operator settings."""
    _runtime.clear()
    _runtime["configured"] = False
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage()
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270
    settings.watching.client_timeout = 300
    load_api_config()
    ha = os.environ.get("SSH_PROVIDER_HA", "true").lower() == "true"
    if ha:
        identity = os.environ.get("POD_UID") or str(uuid.uuid4())
        settings.peering.name = PEERING_NAME
        settings.peering.mandatory = True
        settings.peering.standalone = False
        settings.peering.priority = int(hashlib.sha256(identity.encode()).hexdigest()[:15], 16)
        settings.peering.lifetime = PEERING_LIFETIME
    _runtime.update(
        configured=True,
        ha=ha,
        priority=settings.peering.priority,
        started_at=datetime.now(UTC).isoformat(),
    )


@kopf.on.probe(id="runtime")
def runtime_probe(**_kwargs) -> dict:
    """Liveness stays local; readiness independently checks authenticated API access."""
    return dict(_runtime)
