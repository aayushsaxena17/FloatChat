# Stage 4 plan - natural-language assistant, RAG and benchmark (reviewed 2026-10-12)

Status: **plan written 2026-10-12; implementation in progress** (owner instruction 2026-10-12:
`main` holds the accepted Stage 3 and the dashboard-latency work; build Stage 4 on it on a new
branch; decide open questions without further approval). Scope: build prompt "Stage 4", PRD §5.6,
§5.11, §6.8, §9.2, §10, §13, §14, §16.3, §20.4, §22, §30.1-§30.3. Branch `codex/stage-4` from
`main` at `dff185a`; one pull request into `main`. Decisions taken in this review are ADR-0069 to
ADR-0074.

## 0. What this review changed in the gate's proposed plan

The Stage 3 gate proposed: a chat route over `POST /v1/chat/messages` that turns a question into
a validated `stage2-plan-v1` document, an interpretation panel, pgvector retrieval over the
parameter catalogue and region definitions, prompt-injection controls, the golden benchmark under
`eval/` and the two-model ablation when a second key exists, with the provider abstraction, the
conversation store and the benchmark scoring to decide first. Reviewing that against the merged
code, the build prompt and this host changed the following (the advisor's amendments of
2026-10-12 are folded in):

1. **No LLM key exists on this host.** `.env.txt` holds only the Argovis key and the development
   `.env` holds none; the build prompt lists "New Gemini API key" as an owner-provided item.
   Everything in this stage is therefore built and tested key-independent: the Gemini and the
   OpenAI-compatible adapters are exercised against a fake HTTP transport with the documented
   response shapes, and live verification is listed as pending in the gate report (ADR-0069).
2. **Offline is opt-in, never a fallback.** `LLM_PROVIDER` defaults to `gemini`; without a key the
   chat endpoints answer `llm_unavailable` (503, the PRD §22 "temporary limitation") while every
   other route and readiness stay green. The deterministic `offline` provider (rule-based planner,
   hashed embeddings) is selected explicitly by the tests, the integration stack and the harness,
   and is named wherever it answered: the interpretation panel, the audit record and the report
   (ADR-0069, ADR-0070).
3. **The offline planner's numbers are a harness smoke test, not RQ1.** The report header states
   the provider, that it is not an LLM, and that no key existed on 2026-10-12. The README results
   table carries that label verbatim until the owner runs the harness with a key. The rule-based
   planner, like the prompts, is tuned against the development split only (ADR-0074).
4. **Gold plans pass the live validator.** A test runs every gold plan through `validate_plan`
   and the region fixture. Categories the engine cannot satisfy get a recorded gold kind: BGC
   variables (deferred, PRD §29.10) are `unsupported`; spans beyond `time_span_days` are
   `unsupported` naming the Stage 5 jobs, never a silently narrowed plan (PRD §10.4); dateline
   cases are plan-only (not executable against the Indian Ocean dataset). The benchmark pins the
   reference time `2025-04-01T00:00:00Z` and the planner receives it as "today" (ADR-0074).
5. **`httpx` becomes a runtime dependency** of `packages/core` (it was dev-only); `uv.lock` is
   regenerated and committed because CI runs `--frozen`. The Stage 2 socket denial covers the
   adapter tests: they use `httpx.MockTransport` only.
6. **Conversation ownership before authentication.** Stage 7 brings users; Stage 4 scopes
   conversations to an opaque client identifier the browser generates and sends as
   `X-FloatChat-Client`. Stage 7 maps the identifier to the user (ADR-0072).
7. **One vector column, one dimension.** 768 for both `gemini-embedding-001` (with the manual L2
   normalisation the documentation requires below 3072) and `hash-embed-v1`; uniqueness of a
   semantic document is `(doc_type, key, embedding_model)`, so re-embedding with a real key adds
   rows beside the hashed ones and retrieval filters on the active model (ADR-0071).
8. **Wire format from the reference, not memory.** The Gemini adapter follows the REST reference
   read on 2026-10-12 (`v1beta`, `generateContent` and `streamGenerateContent?alt=sse`,
   `generationConfig.responseMimeType`/`responseJsonSchema`/`thinkingConfig.thinkingLevel`,
   `usageMetadata.promptTokenCount`/`candidatesTokenCount`/`thoughtsTokenCount`, `embedContent`
   and `batchEmbedContents` with `outputDimensionality`); the model names are configuration with
   recorded defaults (ADR-0070).
9. **Prices are configuration, tokens are the backstop.** The price table carries a
   `pricing_version` and the source URL; USD is computed from measured tokens; a daily token cap
   is enforced beside the daily USD cap because tokens are exact and prices are not (ADR-0070).
10. **Injection items in the benchmark and a test** (PRD §10.3, §20.6): user text asking for SQL,
    secrets or "ignore the policy" yields only a validated plan or a controlled error, and no
    configured secret appears in any model request body. The narrative renders as plain text
    (ADR-0073).
11. **`make eval-nl` from a clean checkout means no database**: the harness uses the in-memory
    retriever and the offline provider by default, skips result accuracy and reports it as
    skipped unless `QUERY_DATABASE_URL` is set; `make eval` calls it. A small pytest over a
    handful of items proves the harness in CI; the committed report comes from a local full run
    (ADR-0074).
12. **Classify and plan are one structured call.** Greetings and help are matched by rules; every
    other message goes to the planner, whose structured answer carries the intent
    (`plan`, `clarify`, `unsupported`). This deviates from the PRD §10.2 step list to save one
    model call per message and is recorded (ADR-0072).

## 1. Inputs the merged code provides

- `stage2-plan-v1` (`floatchat_core/query/plan.py`): the one plan representation, `validate_plan`
  with one registered detail per violation, `canonical()` and `plan_sha256`.
- `QueryService` (`floatchat_core/query/router.py`): `parameters()` (variables, units,
  descriptions, QC policies, aggregation units, operations, presentations, named regions, limits,
  attribution), `query(document)` returning plan, result, chart, coverage, execution,
  interpretation and provenance; `coverage_missing` when nothing is committed.
- Named regions (`regions/named_regions.json`, ADR-0060): Arabian Sea, Bay of Bengal, Laccadive
  Sea, Andaman Sea, Indian Ocean (IHO), Indian Ocean, Southern Indian Ocean.
- The API (`apps/api/src/floatchat_api/query_api.py`): the correlation middleware, the error
  registry, typed response models, `openapi.json` and the generated `schema.d.ts`.
- The web app (`apps/web`): routes with `/chat` stubbed, TanStack Query hooks, `ChartPanel`,
  `figuresFromChart`, `DataTable`, `ProvenancePanel`, `CoveragePanel`, the design tokens.
- The dev dataset (ADR-0059): the imported acceptance session, reference time
  `2025-04-01T00:00:00Z`, January-March 2025, Indian Ocean; the shared seed
  (`scripts/science_seed.py`) for the integration project.
- Settings: `DATABASE_URL` (floatchat_app, writes) and `QUERY_DATABASE_URL` (floatchat_query,
  read-only); pgvector 0.8.2 with the `vector` extension since migration 0001.

## 2. Decisions (summary; full text in DECISIONS.md)

- ADR-0069: scope, branch, routes, provider default and offline opt-in, model pins.
- ADR-0070: provider adapter (Gemini, OpenAI-compatible, offline), resilience, cost ledger, caps.
- ADR-0071: semantic corpus, `semantic_document`, embeddings, two retrievers with one ranking.
- ADR-0072: chat flow, one structured planning call, clarification, narration, SSE, the
  conversation store and client ownership.
- ADR-0073: prompt-injection and hallucination controls.
- ADR-0074: golden benchmark, splits, gold kinds, harness, metrics, report, integrity rules.

## 3. Work items

### W1. Migration `0018_semantic_chat` and stores (ADR-0071, ADR-0072)

- `app.semantic_document`: `id`, `doc_type` (`parameter`, `qc_policy`, `aggregation_unit`,
  `operation`, `presentation`, `region`, `region_alias`, `example`, `help`), `key`, `title`,
  `text`, `metadata` jsonb, `content_sha256`, `embedding_model`, `embedding_version`,
  `embedding_dimensions`, `embedding vector(768)`, `valid_from`, `valid_to`, `access_scope`
  (`public` in Stage 4), `created_at`, `updated_at`; unique `(doc_type, key, embedding_model)`.
- `app.chat_conversation` (`id`, `client_id`, `title`, `created_at`, `updated_at`,
  `message_count`) and `app.chat_message` (`id`, `conversation_id`, `seq`, `role`, `kind`,
  `text`, `payload` jsonb, `created_at`; unique `(conversation_id, seq)`).
- `app.llm_call` ledger: `id`, `created_at`, `feature`, `provider`, `model`, `prompt_version`,
  `input_tokens`, `output_tokens`, `thinking_tokens`, `estimated_usd`, `pricing_version`,
  `latency_ms`, `status`, `error_code`, `conversation_id`, `message_id`, `correlation_id`.
- Grants: `floatchat_app` DML on the four tables; `floatchat_query` SELECT on
  `semantic_document`. Python stores in `floatchat_core/chat/store.py` (conversations and
  messages on the app engine) and `floatchat_core/llm/ledger.py` (calls and the daily sums).

### W2. Provider adapter (ADR-0070)

`floatchat_core/llm/`: `provider.py` (the `Provider` protocol: `structured(request)`,
`embed(texts, task)`, `stream_text(request)`; `Usage`, `StructuredResult`), `gemini.py`,
`openai_compatible.py`, `offline.py`, `policy.py` (timeouts, bounded retries on 429/5xx/timeouts,
circuit breaker, the daily USD and token caps, the ledger write, the `llm_unavailable` and
`llm_budget_exhausted` errors), `pricing.py` (the table with `pricing_version` and source URL),
`config.py` (`LlmSettings`, env prefix `LLM_`, plus `GEMINI_API_KEY`, `OPENAI_API_KEY`,
`OPENAI_BASE_URL`).

### W3. Corpus, embeddings and retrieval (ADR-0071)

`floatchat_core/rag/`: `corpus.py` builds the documents from the live catalogue code (variables,
units, descriptions, QC policies, aggregation units, operations, presentations, limits), the
region records plus hand-written aliases (`regions/aliases.json`), help texts and the curated
examples (`eval/corpus/examples.json`, at least 30, disjoint from the held-out split);
`embeddings.py` (`hash-embed-v1`: hashed word and character trigram features, L2-normalised, 768
dimensions; provider embeddings through the adapter); `retriever.py` (`Retriever` protocol,
`MemoryRetriever`, `PgVectorRetriever` with cosine distance filtered by `embedding_model`,
`access_scope` and validity; the same ranking); `scripts/semantic_seed.py` embeds and upserts
(content hash compare, only changed documents are re-embedded) and runs in the integration
project and after `make dev`.

### W4. Chat pipeline (ADR-0072, ADR-0073)

`floatchat_core/chat/`: `prompts.py` (`planner-v1`, `narrator-v1`: the policy, the plan schema
digest, the delimited context with document ids, the delimited user text, the reference time),
`schema.py` (the planner's structured output: `kind`, `plan`, `clarification`, `reason`),
`classify.py` (greeting and help rules), `pipeline.py` (classify -> retrieve -> plan -> validate
-> execute -> sanitise -> narrate, emitting events), `narrate.py` (the bounded result summary,
the deterministic template, the model narrative, the numeric grounding check), `audit.py` (the
record: model, prompt versions, retrieved ids, plan sha256, timings, tokens).

### W5. API (ADR-0072)

`apps/api/src/floatchat_api/chat_api.py`: `POST /v1/chat/messages` (JSON answer, or an SSE stream
when the request accepts `text/event-stream`: `status`, `interpretation`, `result`, `token`,
`message`, `error` events), `GET /v1/chat/conversations`, `GET /v1/chat/conversations/{id}`;
the `X-FloatChat-Client` header; new registered codes `llm_unavailable` (503),
`llm_budget_exhausted` (429), `chat_limit` (422), `client_required` (400). `ChatRuntime` builds
the provider and stores lazily; nothing is constructed for a process that never sees a chat
request. `openapi.json` and `schema.d.ts` regenerated; `API_VERSION` 0.3.0.

### W6. Web `/chat` (PRD §2.2, §9.2, §14)

`apps/web/src/chat/`: `ChatPage.tsx` (conversation list from the server, composer, the thread),
`useChat.ts` (client id in `localStorage`, SSE parsing over `fetch`, TanStack Query for the
conversations), `AssistantMessage.tsx` (status steps, narrative as plain text, clarification
chips, the result through `ChartPanel`/`DataTable`, `ProvenancePanel`), `Interpretation.tsx`
("How FloatChat interpreted your request": time range, geography, depth, variables, QC policy,
operation, presentation, transformation, retrieved documents, provider and model, prompt
version, the plan JSON), the unavailable banner. The stub and the "Soon" badge for `/chat` go.

### W7. Golden benchmark (ADR-0074)

`eval/golden/dev.json` (about 50) and `eval/golden/test.json` (at least 100), schema
`golden-nl-v1`; every item carries `review: "needs human review"`.

### W8. Harness and report (ADR-0074)

`eval/nl/harness.py` (`python -m eval.nl.harness --split test --ablations all`), `make eval-nl`
and `make eval`; `reports/eval_nl_<date>.md`.

### W9. Tests

Section 6.

### W10. Documents and gate

`docs/stage4-gate.md` with the ten most common failure types and examples, PROGRESS.md,
DECISIONS.md, README (chat section, results label), `.env.example` (`LLM_PROVIDER`, `LLM_MODEL`,
`GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_DAILY_USD_CAP`,
`LLM_DAILY_TOKEN_CAP`, no values).

## 4. The planner's structured output

```json
{
  "kind": "plan | clarify | unsupported",
  "plan": { "...stage2-plan-v1 document, when kind is plan..." },
  "clarification": {"missing": ["time_range", "geography"], "question": "..."},
  "reason": "one sentence, when kind is unsupported"
}
```

The plan is validated by `validate_plan` and the region fixture; a `plan` that fails validation
becomes a `clarify` naming the failing fields (never a corrected plan the user did not ask for).
Essential constraints: a time range and a geography. Variables default to temperature and
salinity when the question names none and the operation needs them; QC policy defaults to
`science_ready`.

## 5. Events on the stream

`status` `{step}` for each of `classify`, `retrieve`, `plan`, `validate`, `execute`, `narrate`;
`interpretation` (the audit view); `result` (the query response without the plan, bounded as the
query API bounds it); `token` `{text}` narrative chunks; `message` (the stored assistant message);
`error` (the registered error body). The JSON answer is the `message` payload.

## 6. Tests

- `tests/stage4/test_llm_adapters.py`: Gemini and OpenAI-compatible request bodies and response
  parsing over `httpx.MockTransport`; retries, timeouts, the breaker, caps and the ledger; no
  secret string in any request body.
- `tests/stage4/test_embeddings.py`: `hash-embed-v1` determinism, dimension and normalisation.
- `tests/stage4/test_corpus.py`: the corpus builds, keys are unique, every region has aliases, at
  least 30 examples, every example plan validates, no held-out question appears in the corpus.
- `tests/stage4/test_retriever.py`: memory ranking; the pgvector retriever equals it on the
  disposable database (integration marker).
- `tests/stage4/test_pipeline.py`: the offline provider end to end over a service double;
  clarification on a missing constraint; an invalid model plan becomes a clarification; injection
  texts; the narrative's numbers come from the summary.
- `tests/stage4/test_chat_api.py`: the endpoints over doubles; SSE event order; the client
  header; `llm_unavailable` without a key while the catalogue, floats, profiles and query routes
  and readiness answer (PRD §22).
- `tests/stage4/test_golden.py`: both splits parse, counts, categories covered, every gold plan
  validates, ids unique, no duplicate questions across splits.
- `tests/stage4/test_harness.py`: metrics on hand-made predictions; a four-item run writes a
  report with the required header.
- Web: Vitest for the SSE parser, the interpretation panel, the clarification flow and the
  unavailable state; Playwright `chat.spec.ts` in the integration project with the offline
  provider.
- `scripts/integration.py`: seeds the corpus, runs the chat scenario.

## 7. Out of scope

Historical jobs and exports (Stage 5), forecasts (Stage 6), authentication and quotas (Stage 7),
custom analysis, BGC parameters (deferred), a conversation summary memory beyond the stored
messages, query-plan caching by normalised question (PRD §10.5, later), image or file input.

## 8. Gate

`make eval-nl` writes the report from a clean checkout; prompt and retrieval tuning used only the
development split; chat works in the UI (the local run against the dev dataset and the CI
scenario). The gate report lists the ten most common failure types with examples and what the
owner must do: provide a key, review the gold plans, re-run the harness, and record the test-set
number.
