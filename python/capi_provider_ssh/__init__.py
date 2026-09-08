"""Cluster API infrastructure provider for SSH-reachable hosts."""

from importlib.resources import files

__version__ = files(__package__).joinpath("_version.txt").read_text().strip()

API_GROUP = "infrastructure.alpininsight.ai"
API_VERSION = "v1beta1"
