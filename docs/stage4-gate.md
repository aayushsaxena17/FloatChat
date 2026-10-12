# Stage 4 gate report - natural-language assistant, RAG and benchmark (2026-10-12)

Branch `codex/stage-4` from `main` at `dff185a`; plan [docs/stage4-plan.md](stage4-plan.md);
decisions ADR-0069 to ADR-0074. Owner instruction 2026-10-12: build Stage 4 on `main`, decide
open questions without further approval.

## What was built

| Build-prompt item | Delivered | Evidence |
|---|---|---|
| 1. `semantic_document` and the embedding pipeline; pinned model; seed corpus | Migration `0018_semantic_chat` (one `vector(768)` column, uniqueness per embedding model); corpus of 72 documents generated from the catalogue code: parameter definitions, units, QC flag meanings, policies, aggregation units, operations, presentations, limits, 7 regions with 54 hand-written aliases, help texts, 34 curated examples; `scripts/semantic_seed.py` re-embeds only changed content and retires removed documents; embedding model pinned in configuration (`gemini-embedding-001`, 768 dimensions; `hash-embed-v1` offline) and recorded per row | `tests/stage4/test_corpus.py`, `tests/stage2/test_semantic_store.py` (pgvector ranking equals the in-memory ranking; re-seed embeds 0; retirement), dev stack log `semantic_seed ... documents 72` |
| 2. Provider adapter: Gemini default, structured output, timeouts, retries, breaker, token and cost logging, daily cap | `floatchat_core/llm`: Gemini REST `v1beta` (`responseJsonSchema`, `thinkingConfig`, SSE streaming, `batchEmbedContents`), OpenAI-compatible second adapter, opt-in `offline` rules; `ResilientProvider` with per-call timeout, bounded retries on 429/5xx/timeouts, a circuit breaker, a durable `app.llm_call` ledger, a versioned price table, daily USD and token caps | `tests/stage4/test_llm_adapters.py` (20 cases over `httpx.MockTransport`); live Gemini call **not verified** (no key on this host) |
| 3. Chat flow with clarification, SSE, interpretation panel | classify -> retrieve -> plan -> validate -> execute -> sanitise -> narrate; one structured planning call; `POST /v1/chat/messages` (JSON or `text/event-stream`), `GET /v1/chat/conversations`, `GET /v1/chat/conversations/{id}`; `/chat` route with "How FloatChat interpreted your request" | `tests/stage4/test_pipeline.py`, `test_chat_api.py`; Vitest `src/chat`; Playwright `e2e/chat.spec.ts` passed against the dev stack (`reports/stage4-acceptance-2026-10-12/`) |
| 4. Prompt-injection and hallucination controls | Fixed policy separate from delimited context with document ids; delimited untrusted user text; strict JSON schema; the validator and region catalogue are the authority; a failing model plan becomes a clarification; numbers in a model narrative must appear in the bounded result summary or the template narrative is used; narrative is plain text; audit record on every message; no secret in any request body | `test_pipeline.py::test_injection_text_yields_only_controlled_outcomes_and_no_secret`, `::test_model_narrative_is_kept_only_when_grounded`, `::test_invalid_model_plan_becomes_a_clarification_not_a_corrected_plan`; acceptance `chat-nearest-floats.json` and the injection answer below |
| 5. Golden benchmark in `eval/golden/` | 182 items (61 development, 121 held-out) across the ten PRD §20.4 categories plus scope/injection; 152 plans, 14 clarifications, 16 unsupported; every gold plan passes `validate_plan` and the region fixture; every item `review: needs human review` | `tests/stage4/test_golden.py` |
| 6. `make eval-nl` | ablations `schema_only`, `rag`, `rag_examples`; providers `offline` always, `gemini` and the OpenAI-compatible model when keys exist; plan exact match, seven field accuracies, result accuracy through the API, clarification appropriateness, latency p50/p95, tokens per query, failure taxonomy; report with commit, models, prompt versions, seed | [reports/eval_nl_2026-10-12.md](../reports/eval_nl_2026-10-12.md), `tests/stage4/test_harness.py` |
| 7. LLM unavailable: dashboard and direct queries keep working | `LLM_PROVIDER=gemini` without a key: chat answers `llm_unavailable` (503) and nothing else changes; readiness unaffected | `test_chat_api.py::test_llm_unavailable_leaves_the_rest_of_the_api_working` |

## Acceptance criteria

- `make eval-nl` runs from a clean checkout and writes the report: yes, with the in-memory
  retriever and the offline provider by default (no database or key needed); result accuracy
  needs `--api-url` against a running stack.
- Prompt and retrieval tuning used only the development split: yes. The rule-based planner was
  tuned on the development failures only (63% -> 100% exact on dev with retrieval); the held-out
  split was run once per report and never used to change a rule.
- Chat works in the UI: yes, on the dev stack with the offline provider (screenshot) and in the
  CI integration project (Playwright scenario, API probe in `scripts/integration.py`).

## Numbers (offline provider, held-out split, 121 items)

**These are not LLM numbers.** No Gemini or other key existed on this host on 2026-10-12; the
rule-based planner is the no-model floor of the ablation and the harness's smoke test. The RQ1
result needs the owner's key.

| Ablation | Kind accuracy | Plan exact match | Clarification appropriateness | Result accuracy |
|---|---|---|---|---|
| schema_only | 84.3% | 72.0% | 84.3% | 88.8% (80 executed) |
| rag | 95.0% | 83.0% | 95.0% | 89.2% (93 executed) |
| rag_examples | 95.0% | 83.0% | 95.0% | 89.2% (93 executed) |

The retrieval effect is real even for the rule-based planner: without the retrieved alias
documents it cannot resolve "BoB", "off Oman" or "south Indian Ocean" (named_regions plan exact
match 15% schema-only against 85% with retrieval). Examples add nothing for a planner that does
not read them, as expected. Result accuracy counts executable items whose predicted plan's
`result_sha256` equals the gold plan's; most misses are plan misses.

## The ten most common failure types (held-out split, `rag_examples`)

From the report's taxonomy; one example each. Several are candidates for gold review rather
than planner defects, and are marked so.

1. **wrong_operation** (4): `test-036` "Show the nearest float to 12N 70E in March 2025 on a map": the
   singular "the nearest float" means k = 1; the planner used the default 5.
2. **invalid_plan** (3): `test-030` "between 290E and 300E": 0-360 longitudes are not converted to
   -180..180; the validator rejected the box and the user got a clarification (correct behaviour
   for an uncertain plan, still a miss).
3. **wrong_qc_policy** (3): `test-058` "profiles ... with the original real-time values": gold says
   `raw` (every stored column); the planner kept `science_ready`. Gold review candidate: the
   mapping of "original" to `raw` is a convention recorded in the item note.
4. **missing_clarification** (3): `test-060` "Compare original and adjusted temperature": one plan
   carries one QC policy; gold asks which to show; the planner answered with one policy.
5. **wrong_presentation** (3): `test-077` "Mean and count of temperature per day ... 1-7 March
   2025": gold is a table (no chart word); the planner treats "per day" as a series and drew a
   line chart. Gold review candidate: the dev split uses "daily" for charts and "by day" for
   tables; "per day" sits between.
6. **wrong_geography** (2): `test-022` "in the Arabian Sea and the Bay of Bengal ... by region": gold
   is the envelope region grouped by region; the planner matched the first named region.
7. **unnecessary_clarification** (2, `rag`; 13 in `schema_only`): aliases outside the retrieved
   documents ("Bengal bay" ranked below the cut) leave the planner without a region.
8. **wrong_time_range** (1): `test-012` "since 20 March 2025": the single-day rule fired before the
   open-ended "since" rule.
9. **wrong_variables** (1): `test-095` "Salinity only, no temperature": the word "temperature"
   adds the variable; negation is not modelled.
10. **unsupported_mismatch** (`schema_only`): BGC and export questions are refused correctly in
    every ablation; the schema-only run's `core_bgc_availability` plan misses come from the
    alias-less region matching, not from the refusal rules.

Per-item outcomes are in `reports/eval_nl_2026-10-12.json`.

## Tests and checks

- Python: `ruff check`, `ruff format --check`, `mypy` (strict, 76 files), `export_openapi --check`
  green; the final offline suite run passed 1,948 cases (1 skipped). An earlier run on this
  host failed the three `tests/test_refetch.py::test_real_https_stream_obeys_total_deadline`
  cases ("must reach an actual HTTPS peer"); the same cases failed identically on `main` in a
  clean worktree and passed on the next run, so they are intermittent and environmental.
- Stage 4 suites: 71 unit and contract cases; `tests/stage2/test_semantic_store.py` on the
  disposable PostGIS server (migration 0018, pgvector ranking, store, ledger).
- Web: ESLint, Prettier, `tsc`, Vitest (8 chat cases among 73), production build (entry 144 kB
  gzipped; the chat page adds no new chunk).
- Dev stack: rebuilt with `LLM_PROVIDER=offline`, corpus seeded on start, chat answers through
  the API (JSON and SSE), the held-out harness executed 93 plans through `POST /v1/query`,
  Playwright chat scenario passed.
- CI: green on pull request #13 (all seven jobs; the `integration` job seeds the corpus,
  probes the chat endpoint and runs the chat scenario with the offline provider):
  https://github.com/aayushsaxena17/FloatChat/actions/runs/38294847877.

## Known issues and limitations

- **No live model verification.** The Gemini adapter follows the REST reference as read on
  2026-10-12 and is tested against recorded-shape responses only. The first live call may surface
  a schema-subset rejection of `responseJsonSchema` (the planner schema is flat on purpose) or a
  thinking-level the chosen model does not offer (`thinkingLevel` is configuration).
- **Prices are configuration.** `pricing.py` carries the 2026-10-09 page values with a version
  and source; the ledger flags rows priced at the default; the daily token cap is the hard
  backstop.
- The offline planner's narrative is the deterministic template; the model narrative path (with
  the numeric grounding check) is exercised by tests only.
- Conversations are scoped by a browser-generated client identifier until Stage 7 (ADR-0072).
- The benchmark's gold plans are the builder's drafts; at least 20% should be double-checked by
  a second person and disagreements recorded (PRD §30.2).
- `eval/golden` executable items assume the dev dataset (January-March 2025, Indian Ocean);
  `expected_empty` items execute to an empty result by design.

## Needs from Aayush

1. Provide a Gemini key (and optionally a second, OpenAI-compatible key) in the development
   `.env` (`GEMINI_API_KEY`, `LLM_PROVIDER=gemini`); run `python3 -m scripts.dev seed-corpus`,
   then `make eval-nl` with `--api-url http://127.0.0.1:8000 --providers offline,gemini`. The
   first live call verifies the adapter; the report then carries the real RQ1 number.
2. Review the gold plans in `eval/golden/dev.json` and `eval/golden/test.json` (the ten failure
   types above mark the conventions to decide first), correct them, re-run `make eval-nl`, and
   record the held-out plan accuracy in the README results table in place of the offline label.
3. Review and merge the Stage 4 pull request after CI.
4. ADR-0057, ADR-0059 and ADR-0060 (Stage 2) still await confirmation.

## Proposed plan for Stage 5

Historical jobs and exports (PRD §6.7, §8.4, §9.3, §21.2, §22): `analysis_job` and
`analysis_job_chunk` tables; separate Celery queues (the Stage 1 PostgreSQL work queue is the
precedent to reconcile with, ADR-0047); `POST /v1/exports`, `GET /v1/jobs`, `GET /v1/jobs/{id}`,
`GET /v1/jobs/{id}/events` (SSE, reusing the chat's event writer), `POST /v1/jobs/{id}/cancel`
with idempotency keys and attachment of identical active requests; chunked, resumable historical
retrieval over the Stage 1 pipeline; CSV and Parquet exports with manifest, provenance sidecar,
checksums, counts, citation and signed URLs; the jobs UI; the §22 failure tests; the 10-year
report. The chat's `unsupported` answers for exports and long spans become job creation.
