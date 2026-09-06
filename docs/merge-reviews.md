# Post-merge review log

Record the exact merged commit, relevant CI/publication evidence and any remaining
delivery boundary after each merge. PR follow-up comments retain the final status
when it becomes available after this file's own review. An image publication does
not establish a management-cloud rollout.

## 2026-09-06: P1 and dependency maintenance

| PR | Merged commit | Verification and follow-up |
|---|---|---|
| [#234: P1 lifecycle and HA](https://github.com/alpininsight/capi-provider-ssh/pull/234) | `e2849d3db7a64b56bb9d552d11a5ba571139bd96` | PR lifecycle passed; the subsequent changelog-only merge cancelled this commit's develop runs. The replacement develop run below passed with unchanged runtime inputs |
| [#235: generated changelog](https://github.com/alpininsight/capi-provider-ssh/pull/235) | `f250fc526f22d8a350029704034fcb0cd8537f38` | [Develop CI passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048092499): four Ready nodes, one bootstrap attempt after active-provider failure, recovery observed at 120.5 s. [Multi-platform publication passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048092527) |
| [#236: pinned Actions updates](https://github.com/alpininsight/capi-provider-ssh/pull/236) | `1ed6339063f3154e7acc4b55fdaf562033a12139` | [PR lifecycle and quality passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048242999), [container/version checks passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048242944); follow [develop CI](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048741800) and [publication](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048741774). No runtime dependency change in this PR |
| [#232: Kopf and Kubernetes-client updates](https://github.com/alpininsight/capi-provider-ssh/pull/232) | `60a9d13527bba12b984c2df0b3e21e1f2b2a937c` | [Updated PR lifecycle passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048385973), [develop CI passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34049035814) and [publication passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34049035785). Python 3.14 is checked in the combined follow-up #230 |
| [#231: hooks and changelog normalization](https://github.com/alpininsight/capi-provider-ssh/pull/231) | `25cec5e2c6d09ede8fe92d19cf625d29e15d6cf4` | [All PR checks passed](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34048895074), including the new full hook job. Merged through the existing authenticated GitHub browser because the CLI OAuth token lacked workflow scope; no permission expansion or rule bypass |
| [#239: API and peering readiness](https://github.com/alpininsight/capi-provider-ssh/pull/239) | `3e3cbcc1b91998e2230a16f1b973be2c9506848c` | PR checks and image publication passed. The develop run was cancelled by #240; its replacement exposed the probe memory issue below. The image has not been promoted to management-cloud |
| [#240: generated changelog](https://github.com/alpininsight/capi-provider-ssh/pull/240) | `119b9540a81367b00234dcc5f758951b76b97410` | User merged after all PR checks passed; runtime inputs were unchanged. [Replacement CI](https://github.com/alpininsight/capi-provider-ssh/actions/runs/34062084208) caught an exec probe exiting 137 despite printing ready; publication alone was not accepted as rollout evidence |

The image published for `f250fc5` is
`ghcr.io/alpininsight/capi-provider-ssh-python@sha256:defc3b65e982932eb9e6fcc43f578df6c0ef0133091f492222d774e5df71e2f7`.
This records source/publication evidence, not the live provider image. The default
branch had zero open Dependabot vulnerability alerts at this review.

| Recurring issue or ambiguity | Concrete improvement | Owner / evidence |
|---|---|---|
| Green dependency checks were produced before new P1 tests existed | Update old PR branches, require the current API/lifecycle/failover lane and inspect its artifacts before merging | Maintainer; #231 and #232 branches updated before review |
| The Python 3.14 image update retained a Python 3.13 installer-cleanup path | Resolve the standard-library path with `sysconfig`; assert absence of `pip` and `ensurepip` in both image interpreters | Runtime/CI; #230 correction and image smoke test |
| Image interpreter and Python unit-test versions diverged | Run quality on 3.13 and 3.14, test the built image in Kind, use unique artifact names per matrix job | Runtime/CI; #230 quality matrix |
| Generated changelog whitespace repeatedly failed local hooks although GitHub CI was green | Strip trailing horizontal whitespace in git-cliff postprocessing; run every configured file hook in CI, including generated files | CI; #231, reproduced with the workflow's git-cliff 2.7.0 |
| A changelog-only merge cancelled source publication/testing via develop concurrency | Inspect the replacement run and compare runtime inputs; do not label a cancelled run as success. Future trigger/concurrency changes must preserve a verifiable source-to-image record | Maintainer; #234/#235 evidence above |
| `gh pr merge --auto` suggested a CI gate although develop rules required no status checks | Explicitly verify every current PR check before merging; repository administrators should make quality, hooks, lifecycle, manifest, image and version checks required | Repository administration; rules inspected on 2026-09-06, no protection bypass used |
| A generic CLI merge-policy error hid missing OAuth workflow scope | Confirm the scope error, use existing authorized SSH pushes and normal GitHub browser merges; do not bypass branch rules or silently expand token permissions | Maintainer; #231 browser showed all checks passed and regular merge eligibility |
| The local CAPI upgrade used server-side apply while Argo used client-side apply | Test the actual GitOps apply strategy for large CRDs, inspect served/storage versions and controller cache health; Ready replicas alone are insufficient | GitOps; #6544 follow-up, dated live failure in the support matrix |
| Both provider probes used local liveness, so a replica without API connectivity was Ready | Separate API/coordination readiness from liveness; require the current process's own fresh peer and test unreachable API, stale peers and healthy standby behavior | Provider; follow-up to #234 and k8s #6557 |
| A control-plane VM lacked the already defined persistent cloud-subnet route | After VM creation or address migration, verify both the persistent route file and the kernel route, Cilium API status, endpoint identity and Pod-to-API access | Platform; k8s #6557, existing `k8s_node_baseline` route contract |
| The full Kubernetes SDK in each readiness exec consumed about 104 MiB; overlapping processes exceeded the 256 MiB cgroup limit | Use a small TLS-verified in-cluster client, test token rotation/denials and simultaneous probes, assert zero OOM kills/restarts; use the requested 128/512 MiB Burstable budget | Provider/CI; local bounded reproduction killed both operator and probe, following #240's exit 137 |
| Changelog generation succeeded but `--auto` failed with `Pull request is in clean status` | Gate the current checks explicitly and distinguish normal clean-head merge eligibility from enabling auto-merge; preserve the actual failure category instead of diagnosing permissions generically | CI maintainer; #240 post-merge review records the proposed state-machine coverage |

Upstream sources checked during review: [Python sysconfig](https://docs.python.org/3.14/library/sysconfig.html#installation-paths),
[Python 3.14 changes](https://docs.python.org/3.14/whatsnew/3.14.html),
[git-cliff postprocessors](https://git-cliff.org/docs/configuration/changelog/#postprocessors),
[pre-commit-hooks 6.0 migration](https://github.com/pre-commit/pre-commit-hooks/releases/tag/v6.0.0),
and [setup-kubectl 5.1.0 release](https://github.com/Azure/setup-kubectl/releases/tag/v5.1.0).
