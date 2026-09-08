# capi-provider-ssh (Python)

Cluster API infrastructure provider for existing SSH-reachable hosts. It consumes
CAPI bootstrap data and manages UID-bound host claims, bootstrap, cleanup and
in-band reboot remediation. It currently implements the legacy **v1beta1 CAPI
contract**; its own CRDs also use `v1beta1`.

Start with the [repository overview](https://github.com/alpininsight/capi-provider-ssh)
and [documentation index](https://github.com/alpininsight/capi-provider-ssh/tree/main/docs).
The [support matrix](https://github.com/alpininsight/capi-provider-ssh/blob/main/docs/support-matrix.md)
defines validated versions and limits. Deploy through the documented management
cluster manifests and immutable container image; installing this Python package
alone does not install CRDs, RBAC or CAPI controllers.

Release builds take `PROVIDER_VERSION` from the same GitVersion calculation as
the container workflow: `v0.4.3` becomes Python version `0.4.3`, and
`0.5.0-alpha.12` becomes `0.5.0a12`. Other branch prereleases are development
versions with a losslessly encoded local label. Unversioned source builds identify
themselves as `0.0.0+unversioned`; they make no release claim. Source archives
retain their build version for subsequent offline wheel builds.

The package includes the repository's MPL-2.0 license. See the
[maintenance policy](https://github.com/alpininsight/capi-provider-ssh/blob/main/docs/maintenance-policy.md)
for supported release lines and backports, and use
[private vulnerability reporting](https://github.com/alpininsight/capi-provider-ssh/security/advisories/new)
for security findings.
