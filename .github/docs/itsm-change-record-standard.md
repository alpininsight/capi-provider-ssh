# ITSM Change Record Standard for Provider Repositories

## Purpose

Define a practical, auditable change record model for this repository that is
compatible with enterprise change governance while remaining lightweight enough
for startup teams.

## Scope

Applies to provider changes promoted through `develop -> main`, including code,
release metadata, and published container artifacts.

## What is Standardized vs Organization-Specific

| Area | Standardized by ISO/ITIL | Organization-specific |
| --- | --- | --- |
| Change control process existence | Yes | No |
| Required evidence and traceability | Yes (process outcome required) | No |
| Exact ticket form fields and workflow states | No | Yes |
| CAB/approval model and risk thresholds | No | Yes |
| Tooling (ServiceNow/Jira/GitHub-only) | No | Yes |

## Minimum Change Record Schema

Use these fields for every normal change:

1. `change_id`: Internal ITSM ID or GitHub-based surrogate ID.
2. `title`: One-line change intent.
3. `type`: `standard`, `normal`, or `emergency`.
4. `service_scope`: Systems and environments affected.
5. `risk_and_impact`: Impact, blast radius, rollback complexity.
6. `implementation_plan`: Concrete execution steps.
7. `validation_plan`: Tests and acceptance checks.
8. `backout_plan`: Rollback steps and trigger conditions.
9. `approvals`: Required approvers and approval timestamps.
10. `execution_window`: Planned start/end UTC timestamps.
11. `evidence_links`: Issue, PRs, workflow runs, release, image digest.
12. `post_implementation_review`: Outcome, incidents, follow-ups.

## Mapping to GitHub Artifacts

| Change record field | GitHub evidence |
| --- | --- |
| Problem statement | GitHub Issue |
| Proposed remediation | Fix PR into `develop` |
| Promotion approval | Release PR `develop -> main` |
| Test evidence | GitHub Actions checks and run logs |
| Released version | GitHub Release tag |
| Deployable artifact | GHCR image tag + digest |
| Closure evidence | Closed issue + merged PR links |

Example sequence in this repo:

- Issue: `#127`
- Fix PR: `#128` (`fix/issue-127-no-bootstrap-rerun -> develop`)
- Release PR: `#130` (`develop -> main`)
- Release: `v0.3.5`
- Container: `ghcr.io/alpininsight/capi-provider-ssh-python:v0.3.5`

## Automation Boundary

Automated:

- CI checks
- Release/tag publication
- Container build and publish
- Immutable artifact metadata (tags/digests/run logs)

Manual/controlled:

- Risk classification
- Approval decisions
- Merge decisions
- Final operational sign-off

## Standard Operating Flow for this Repository

1. Open an issue with reproducible impact and acceptance criteria.
2. Implement on `fix/*` or `feat/*` branch and open PR to `develop`.
3. Require successful checks and required approvals.
4. Merge to `develop`.
5. Open release PR from `develop` to `main`.
6. Merge release PR after checks pass.
7. Confirm release tag and container digest.
8. Close issue with final evidence links.

## How This Document Was Derived

Method used on 2026-02-24:

1. Reviewed official ISO pages for ISO/IEC 20000 normative and guidance
   publications.
2. Reviewed ISO/SC40 public resources for free templates/guidance.
3. Reviewed official PeopleCert ITIL pages for Change Enablement practice
   framing and publication access model.
4. Mapped those governance requirements to this repo's existing GitHub flow.

## References (Retrieved 2026-02-24)

1. ISO/IEC 20000-1:2018 standard page:
   https://www.iso.org/standard/70636.html
2. ISO/IEC TS 20000-5:2022 guidance page:
   https://www.iso.org/standard/81164.html
3. ISO/SC40 service management resources (includes free template assets):
   https://committee.iso.org/sites/jtc1sc40/home/resources/content-left-area/service-management-resources/iso-iec-20000-1-2018.html
4. ISO/SC40 Service Management Plan template PDF:
   https://committee.iso.org/files/live/sites/jtc1sc40/files/SM%20Plan%20template%20SC40-2%20202501
5. ITIL 4 Practitioner: Change Enablement (PeopleCert):
   https://www.peoplecert.org/browse-certifications/it-governance-and-service-management/ITIL-1/itil-4-practitioner-change-enablement-3794
6. PeopleCert library/access model for ITIL practice publications:
   https://www.peoplecert.org/Membership/peoplecert-library
7. ISO/IEC TS 20000-11 relationship to ITIL page:
   https://committee.iso.org/sites/jtc1sc40/home/wg2/publications/iso-iec-ts-20000-11.html
