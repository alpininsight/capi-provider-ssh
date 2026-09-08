# Container delivery

The provider is distributed as a public OCI container image:
`ghcr.io/alpininsight/capi-provider-ssh-python`. The existing `-python` package
name is the image's stable distribution name; its source repository is
[`alpininsight/capi-provider-ssh`](https://github.com/alpininsight/capi-provider-ssh).

## Find the right artifact

| Location | Purpose | What to verify |
|---|---|---|
| [GitHub Releases](https://github.com/alpininsight/capi-provider-ssh/releases) | Release notes and the source tag | The intended stable version and source commit |
| [Container package](https://github.com/alpininsight/capi-provider-ssh/pkgs/container/capi-provider-ssh-python) | Pullable image versions in GHCR | The version's tags, publication time and immutable digest |
| [GitHub Actions](https://github.com/alpininsight/capi-provider-ssh/actions) | Build/test results and retained run artifacts | The matching source SHA, completed jobs and publication output |
| [Organization linked artifacts](https://github.com/orgs/alpininsight/artifacts) | Storage and deployment metadata supplied by workflows or integrations | Whether a record describes publication or an observed deployment |

The package card's original publication date does not establish the age of an
individual version. Inspect that version's details. A GitHub release is separate
from an image publication and can finish first. Linked artifacts contains
metadata records rather than the image files or the Actions test-artifact
downloads; an empty page does not establish a missing container.

## Pull and pin

The verified `v0.4.5` example is available in the
[release](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.5) and
[matching package version](https://github.com/orgs/alpininsight/packages/container/capi-provider-ssh-python/1224368847).
This is a reproducible versioned example, not an automatically updated latest
version recommendation. Check the [support matrix](docs/support-matrix.md) and
the intended release before upgrading.

```bash
docker pull ghcr.io/alpininsight/capi-provider-ssh-python:v0.4.5

# Immutable multi-platform index for this release.
docker pull ghcr.io/alpininsight/capi-provider-ssh-python@sha256:1d6f3debc48ac8727e3e54ea11b9be5c68ce41f161376017fb74a0ce3f3e8247
```

The index contains `linux/amd64` and `linux/arm64` images with SBOM and build
provenance. Registry interfaces may also show attestation descriptors as
`unknown/unknown`; those are metadata, not another supported runtime platform.
Use the immutable index digest in GitOps. Channel tags such as `develop` and
`latest` move and are intended for discovery.

For a stable release, compare the source tag, OCI version, installed Python
package identity and SPDX license across both architectures. The
[release process](docs/release-process.md) defines the evidence chain. Retain
old release tags and digests, including the documented
[v0.4.4 identity mismatch](docs/support-matrix.md#v044-package-identity-notice).

## Build and test dependencies

| Component | Current role | Authoritative reference |
|---|---|---|
| `python:3.14-slim` | Provider runtime; base image is digest pinned | [Python Dockerfile](python/Dockerfile) |
| `ghcr.io/astral-sh/uv` | Locked Python dependency installation; copied from a digest-pinned image | [Python Dockerfile](python/Dockerfile), [lockfile](python/uv.lock) |
| Kind node and CAPI controller images | Disposable integration and lifecycle test clusters | [Testing guide](docs/testing.md), [CI configuration](.github/workflows/ci-python.yml) |

Read exact pins from the corresponding source revision. An offline environment
must mirror the images and Python artifacts required by that revision; pulling
a few moving base tags is insufficient to establish an offline installation.
Deployment prerequisites and the current installation boundary are documented
in [installation](docs/installation.md).

## Delivery ownership

Public product documentation describes available images and how to consume
them. Publication infrastructure is maintained separately. A registry migration
requires a verified replacement image and a separate consumer digest change;
the existing registry reference remains valid until that transition is proven.
Publication alone does not change the running provider in a cluster.

References: [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[linked artifacts](https://docs.github.com/en/code-security/concepts/supply-chain-security/linked-artifacts).
