# S1-SOURCE-2 — acceptance decision proposal (now ACTIVE under stage1-v3)

Status: **ACTIVE under stage1-v3** per ADR-0040 (owner authorization ADR-0039, advisor
agreement 2026-10-08), for runs admitted with `RUN_POLICY.source_policy = "S1-SOURCE-2"`.
The receipt clause was matched to the observed deployment body (HTTP 404,
`application/json; charset=utf-8`, the 5-byte empty array `[\n\n]\n`) instead of the
byte-exact `[]` below; ADR-0040 and contract §3.2 hold the active wording (any charset,
raw body <=64 bytes parsing to exactly an empty JSON array). The rest of this document is
the historical proposal as reviewed under stage1-v2, which stays in force for earlier
runs: the 44 failures and 8 quarantines are unchanged and no discovery, capture or
alternate-source adapter is authorized by it.

## Decision A: retain the existing requirement

Contract §§3.2, 8 and 12 and cases G04, G05, C03, F02 and F05 continue to require coherent
complete selections, strict HTTP failures, whole-chunk quarantine, zero quarantined
leaves and zero coverage gaps. A collection 404 is a failed selection. A profile
with `degenerate_levels` blocks its entire selection.

The 44 historical failures contain status/role evidence only, all before inventory
was established. Their bodies, framing, source identity sets and before/after
agreement are unavailable. They cannot be certified empty retrospectively.

To close A, the affected selections need a newly authorized, complete coherent
inventory/profile/inventory observation from a compatible service, or independent
source evidence establishing every eligible observation and its absence/presence
over those exact selections. To close discarded-input completeness, obtain corrected
source profiles without discarded components, or independently enumerate the
discarded inputs and compare all original and adjusted core values, QC, units,
modes, levels, revisions and identities against a corrected complete representation.
A clean returned pressure vector, an inventory ID, or the current synthetic translator
models cannot establish that comparison. Offline evidence presently cannot close A.

## Decision B: smallest recommended qualified population

Recommendation: review B as a separately versioned acceptance amendment, retaining
all existing safety and resource limits. Approval of the population definition
alone must not activate the optional 404 or exclusion rules. Their implementation,
deployment evidence and separately bounded owner execution remain distinct gates.

Proposed exact replacement for the acceptance population and completeness clause:

> S1-SOURCE-2 acceptance evaluates eligible, structurally valid profiles delivered
> by the pinned and deployment-validated Argovis selection interface. It does not
> certify a census of underlying Argo/GDAC observations, inputs discarded by that
> interface, or completeness of affected scientific measurements. Successful
> delivery coverage requires a coherent bounded inventory-before, data=all profile
> response and inventory-after for every terminal accepted leaf. All returned IDs
> and occurrences must reconcile to accepted, filtered, duplicate or explicitly
> excluded outcomes. Unresolved transport, HTTP, framing, inventory, unknown-warning
> or schema failures remain failures or quarantines and prevent acceptance.

Proposed exact **optional**, independently approved 404 clause for §3.2/G05:

> Only `/argo` collection selections using exactly startDate, endDate and polygon
> for inventory_before/inventory_after and those parameters plus data=all for
> profile may use a validated empty-delivery receipt. No id search or `/argo/meta`
> request qualifies. Each of the three responses must independently be a complete
> captured response within existing compressed/decompressed bounds, HTTP 404,
> application/json (optional UTF-8 charset), with verified framing and the exact
> empty JSON array body []. All three parameter sets must identify the same
> selection, both inventory roles must omit data, and the profile role must use
> data=all. A mixed 200/404 triple, a nonempty document, error object, missing body,
> malformed/truncated JSON, unknown parameter, mismatched selection, unexpected
> content type or incompatible deployment fails closed. Three coherent 200 empty
> arrays retain their existing behavior. Metadata/single-ID 404s remain failures.
> The receipt proves “no service-returned eligible documents,” never “no source
> science.” The 44 historical status-only failures remain failed coverage.

The pinned release implementation supports a narrower interpretation of zero
surviving documents; it is **not** a deployed-response attestation. Before reviewing
activation, owner-authorized bounded validation must show actual status, complete
sanitized bodies, byte/framing evidence and content types for the exact roles and
supported parameters; identify the deployed source behavior/version or obtain
upstream confirmation binding it to the reviewed implementation. The required
three-404-array rule is deliberately conservative: if the deployment returns an
error envelope instead, this proposal does not silently accept it. No candidate
selection or live command is issued until its bounds and purpose are approved.

Proposed exact **optional**, independently approved exclusion clause for §8/F04/F05:

> The known warning degenerate_levels may produce a profile_excluded_source_loss
> outcome only after an explicitly versioned profile-exclusion amendment is active.
> Exclude the entire affected profile from incoming scientific publication; preserve
> its complete immutable sanitized raw evidence, attribution, checksum, source ID,
> all request selections and warning in an exclusion ledger. Never accept its
> returned core measurements as complete. Record returned levels separately from
> lost input levels; lost levels remain unknown unless independent source evidence
> quantifies them. Previously committed science is retained under the no-tombstone
> rule. Unaffected peers may publish only under this reviewed rule. Unknown warnings,
> missing profile identity or schema drift still quarantine the whole chunk.
> Qualified acceptance requires zero unresolved quarantines and zero unresolved
> delivery gaps AND a complete explicit exclusion ledger. Exclusions are not
> renamed quarantine successes; the report declares
> acceptance_qualified_with_source_exclusions and never scientific_source_complete=true.
> An exclusion count of zero
> does not prove the absence of upstream discarded observations.

Coverage/report amendments: retain separate payload/profile/level denominators;
show delivered, eligible, accepted, filtered, duplicate, excluded and unresolved
counts; exclude no ID from the delivery denominator. Persist per-ID affected
selections, returned-level counts and known/unknown lost-level counts. Freeze both
strict scientific-completeness=false/unknown and qualified delivery completeness.
Persist policy ID, approval artifact, deployment attestation, source pins and
receipt/exclusion references. A selector continues to expose only committed active
generations. Historical eight quarantines are unchanged; this amendment applies
only to future separately authorized runs with its version recorded at admission.

## Review tests and activation gates

`tests/stage1/test_inactive_source_policy.py` exercises a standalone proposal oracle,
not a runtime adapter. It checks exact roles/parameters, complete bounded framing,
content type, coherent three-response outcomes, mixed and malformed rejection,
metadata/id rejection and explicit exclusions with unknown lost levels. A separate
assertion verifies the production failure and warning paths remain strict. These
tests cannot substitute for deployed compatibility, authentic discarded-input
reconstruction, approval, actual-head CI or regional acceptance.

Public source evidence and checksums remain pinned in
`reports/stage1-http-source-semantics.json` and
`reports/stage1-discarded-input-science.json`. The [release service](https://github.com/argovis/argovis_api/blob/13e634127a3ad51e7c237c1319dba4f56fcabf13/nodejs-server/service/ArgoService.js)
and [translator](https://github.com/argovis/ifremer-sync/blob/cbf2bb48ed5d95532c18bb2cd5217e44618356cf/util/helpers.py)
support this distinction between delivered documents and underlying scientific inputs.
