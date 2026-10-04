# Published Stage 0 history remediation

The owner explicitly authorized tested publication in this session. The active dirty Windows checkout was never rewritten, staged, reset or cleaned. Existing work and configuration were preserved and verified first; see `reports/stage0-preservation.json`. Contaminated backups, original mirror, raw diagnostics, replacement expressions and the 33-entry old-to-new commit map are restricted outside Git and OneDrive. The local directory pointer is `%TEMP%/FloatChat-stage0-completion-location.txt`; the first preparation backup is retained separately under `%TEMP%/FloatChat-stage0-location.txt`. Windows may clear temporary storage, so retain preservation material through recovery.

## Executed scope and validation

All advertised branches and tags were fetched into an independent mirror. Seven branches were affected: `Ankita`, `Piyush`, `anuvansh`, `anuvansh2`, `ashmit`, `data`, and `main`. No tags or pull-request refs were advertised at inventory. Initial full-history scanning found eight GCP API-key occurrences; only fully redacted finding identifiers are committed. See `reports/stage0-history-findings.json`.

Git-filter-repo 2.47.0 replaced the credential pattern in file contents and commit/tag messages and removed the January dataset path and its two historical blobs. The exact path was `indian_ocean_profiles_01Jan2025_31Jan2025.parquet`. Other monthly scientific datasets were outside this removal scope and were retained. No pickle was deserialized. Original authors/committers and timestamps were verified for all 31 retained commits; two commits became empty and were pruned. Every retained tree entry was compared to its original, permitting only credential replacement and dataset removal.

Gitleaks 8.30.1 scanned the candidate and a separate validation clone's complete history. Directory scans passed for all seven branch-tip trees. Scans used upstream defaults, the recorded cache/dependency exclusions, 100% redaction, and decode depth 3. No known credential was allowlisted. These checks establish the recorded rules and ref scope, not universal detection of every possible secret.

The tested candidate was published with one atomic push and explicit per-ref force-with-lease values. All remote IDs were rechecked immediately beforehand. Only the seven affected branches were updated; no branch or tag was deleted, and no internal checkpoint/backup ref was published. Main's force-push setting was temporarily changed for publication, then immediately disabled again. The existing two-review rule was retained and all six required checks added. Before/after evidence is in `reports/stage0-protection-before.json`, `reports/stage0-protection-after-publication.json`, and the final protection report.

Before/after ref inventories and sanitized validation metadata are in `reports/stage0-rewrite.json`. The full commit mapping remains outside Git and CI artifacts. The authorized `Proxpekt/FloatChat` URL redirects to the same repository under `aayushsaxena17`; repository identity and administrative access were checked.

A completely fresh remote clone fetched all advertised heads/tags, passed separate directory/full-history scans, matched the published candidate IDs and showed neither removed dataset blob reachable. See `reports/stage0-fresh-published.json`. Final foundation and merged-main verification are recorded in the gate report.

## Old-clone recovery

Stop pushes from old clones. Preserve unpublished work in a restricted, non-synced location and sanitize it. Create a new clone from `https://github.com/Proxpekt/FloatChat.git`; do not fetch or merge contaminated ancestry into it. Reapply reviewed source changes as new commits, rather than merging or blindly cherry-picking old commits. Use the restricted commit map to match old work with sanitized commits. Scan current files and full history before pushing. Never publish internal checkpoint or backup refs. Keep the original dirty Windows checkout as preservation material and use the fresh Ubuntu checkout for development.

Four pre-existing forks and provider caches are outside the authorized origin's branch/tag scope. Fork owners must replace their contaminated history; GitHub Support may be needed to purge cached old objects. No unauthorized fork changes or collaborator messages were sent. The Stage 0 pull request documents this recovery procedure for collaborators.
