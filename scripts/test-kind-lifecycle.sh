#!/usr/bin/env bash
# Owns one disposable Kind cluster. Never reads the default kubeconfig.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TASK_DIR=$(mktemp -d)
TEST_CLUSTER="capi-ssh-ci-$(date +%s)-$$"
export KIND_TEST_KUBECONFIG="$TASK_DIR/kubeconfig"
export KIND_TEST_ARTIFACTS="${KIND_TEST_ARTIFACTS:-$ROOT/python/test-artifacts/kind}"
export KIND_SSH_TARGET_IMAGE=capi-ssh-kubeadm-target:p1
mkdir -p "$KIND_TEST_ARTIFACTS"
cleanup() {
  result=$?
  # Preserve the controller and its ownership records for local failure diagnosis.
  if [[ "$result" != 0 && "${CI:-false}" != true ]]; then
    echo "Test failed; retained $TEST_CLUSTER and kubeconfig $KIND_TEST_KUBECONFIG for diagnosis" >&2
    exit "$result"
  fi
  # Target containers are removed by pytest only after CAPI cleanup succeeds.
  # CI destroys its ephemeral VM even when remote cleanup failed.
  kind delete cluster --name "$TEST_CLUSTER" --kubeconfig "$KIND_TEST_KUBECONFIG" || true
  rm -rf "$TASK_DIR"
  exit "$result"
}
trap cleanup EXIT
kind create cluster --name "$TEST_CLUSTER" --kubeconfig "$KIND_TEST_KUBECONFIG" \
  --config "$ROOT/python/tests/kind/cluster.yaml" \
  --image kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d --wait 180s
docker build -t capi-provider-ssh:kind-test "$ROOT/python"
kind load docker-image --name "$TEST_CLUSTER" capi-provider-ssh:kind-test
docker build -t "$KIND_SSH_TARGET_IMAGE" -f "$ROOT/python/tests/kind/target.Dockerfile" "$ROOT/python"
cd "$ROOT/python"
uv sync --frozen --dev
uv run python -m tests.kind.install
INTEGRATION_TESTS=1 uv run pytest -q -m integration
KIND_LIFECYCLE_TESTS=1 uv run pytest -q -m kind
