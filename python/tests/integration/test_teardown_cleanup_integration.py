"""Integration coverage for deterministic test namespace teardown."""

from __future__ import annotations

import pytest

from tests.integration.cleanup import teardown_test_namespace

pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]


def test_teardown_is_idempotent(core_api, custom_api, test_namespace):
    """Calling teardown repeatedly should be safe and non-failing."""
    teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace=test_namespace)
    teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace=test_namespace)


def test_teardown_refuses_non_test_namespace(core_api, custom_api):
    """Guardrail: never operate on non-test namespaces."""
    with pytest.raises(ValueError, match="Refusing teardown for non-test namespace"):
        teardown_test_namespace(core_api=core_api, custom_api=custom_api, namespace="default")
