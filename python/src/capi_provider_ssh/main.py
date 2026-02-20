"""Kopf entrypoint for capi-provider-ssh."""

import logging
import os

import kopf

# Import controllers to register their handlers with kopf
import capi_provider_ssh.controllers.sshcluster  # noqa: F401

logger = logging.getLogger(__name__)

# Runtime configuration (environment variables)
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "30"))
SSH_COMMAND_TIMEOUT = int(os.environ.get("SSH_COMMAND_TIMEOUT", "300"))
RECONCILE_INTERVAL = int(os.environ.get("RECONCILE_INTERVAL", "60"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "10"))


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_kwargs):
    """Configure kopf operator settings."""
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 270
    settings.watching.client_timeout = 300
