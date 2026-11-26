# Documentation scope and review checklist

This repository documents the open source provider: what it does, how to
install and use it, its supported boundaries, and how to contribute. A reader
must be able to follow the product documentation without access to a company
network, private repository or internal service process.

## Where information belongs

| Information | Public product repository | Operator's private service records |
|---|---|---|
| Product purpose, role explanation and resource lifecycle | Yes | Link to the public source rather than maintain a fork |
| CRDs, examples, installation, SSH trust, cleanup and recovery semantics | Yes; reproducible and environment-neutral | Document only deployment-specific choices |
| Compatibility, limitations, security reporting and actual review policy | Yes; do not hide support gaps or governance exceptions | Internal evidence and administration details as needed |
| Product defects, public CI evidence and reusable lessons learned | Yes; sanitized and source-linked | Detailed operational incident evidence |
| Actual host inventory, placement labels, internal endpoints and registry routing | No | Yes, access controlled |
| Service ownership, customer scope, SLA/SLO, maintenance windows and escalation | No | Yes, with explicit approval and evidence |
| Internal change/continuity forms and environment traffic cutover | No | Yes |
| Credentials, private keys, kubeconfigs, bootstrap Secrets or raw sensitive logs | Never | Use approved secret/evidence storage; never ordinary Git files |
| License, NOTICE, attribution, public API group, image coordinates and security contact | Retain the authoritative public identity | Do not relabel copied open source material as proprietary |

The public API group and registry/project organization are product identifiers.
They remain public even when they contain the maintainer organization's name.
Generic GitOps, HA, security and release instructions also remain public.
Separating an operator's service documentation does not create an enterprise
software edition, additional supported features or a commercial SLA.

## Review every documentation change

1. Name the audience and explain the task before field-level details. Use the
   [getting-started walkthrough](getting-started.md) for role questions.
2. Cross-check behavior, field names, defaults and privileges against code/CRDs.
   Distinguish implemented features, proposals and historical observations.
3. Use synthetic examples and documentation addresses. Exclude actual inventories,
   private repository links, deployment receipts and internal service processes.
4. Check local links and section anchors. Public contributor instructions must
   use public sources; references to another repository in the same organization
   require its inclusion in the reviewed public-reference policy.
5. State prerequisites, acceptance and recovery for every procedure. An example
   fragment must not be presented as a complete installation or workload cluster.
6. Preserve factual license/attribution and public security/support information.
   Do not improve the appearance of assurance by hiding a review exception.
7. Run `python3 scripts/check-documentation.py` and the configured file hooks.
   The guard catches broken local links and unapproved same-organization GitHub
   references; it does not replace human review for sensitive content.

[CONTRIBUTING.md](../CONTRIBUTING.md) makes this part of PR review. The
[documentation index](README.md) separates explanation, procedures, reference and
historical evidence. Reusable escaped defects go into [merge reviews](merge-reviews.md).

## Moving an internal document

Preserve the original with its source revision and checksum in the approved
private destination before removing its current public copy. Keep useful generic
product guidance public and update all incoming links and index configuration.
Historical Git commits, tags, existing releases, PR discussions and external
indexes are not removed by deleting a current file. A genuine secret exposure
requires a separately coordinated security response and credential rotation;
never silently rewrite published history as documentation cleanup.
