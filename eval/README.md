# Evaluation

Stage 4 (ADR-0074): the natural-language-to-plan benchmark and its harness.

- `golden/dev.json` (development split, about 60 items) and `golden/test.json` (held-out split,
  more than 100 items), schema `golden-nl-v1`. Each item: `id`, `category` (the PRD §20.4
  categories plus `scope_injection`), `question`, `gold` (`plan` with a planner-shaped plan,
  `clarify` with the missing fields, or `unsupported`), `ambiguous`, `executable`,
  `expected_empty`, `notes`, `review`. The reference time is `2025-04-01T00:00:00Z`; time ranges
  are inclusive start, exclusive end; depths are decibars. Every gold plan passes the live
  validator (`tests/stage4/test_golden.py`). All items carry `review: needs human review` until
  the owner reviews them.
- Conventions the gold plans follow (decide these first when reviewing): "monthly" and "daily"
  series are `line_chart`; "by month" and "by day" without a chart word are tables; "within X km
  of" lists profiles, "nearest" ranks them (default k 5, radius 500 km); "below X" is X to the
  maximum depth; "around X" is a 100 dbar band; "surface" is 0-10 dbar; "original values" on a
  profile read is `raw`, "regardless of QC" is `mode_selected`; metres are decibars; BGC,
  exports, forecasts and spans beyond 366 days are `unsupported`; two regions become the envelope
  region grouped by region.
- `nl/harness.py`: `make eval-nl` (equivalent to
  `python -m eval.nl.harness --split test --ablations all`). Options: `--split dev|test|all`,
  `--ablations schema_only,rag,rag_examples`, `--providers auto|offline,gemini,openai`,
  `--api-url http://127.0.0.1:8000` (result accuracy through `POST /v1/query`), `--limit`,
  `--seed`, `--out`. Writes `reports/eval_nl_<date>.md` and a JSON sidecar with per-item results.
- Tuning rule: prompts, retrieval and the offline planner are tuned on the development split
  only. A report produced with the `offline` provider says in its header that it is not an LLM
  result.
- Curated examples embedded for retrieval live in
  `packages/core/src/floatchat_core/rag/examples.json` and are disjoint from the held-out split
  (a test enforces it).
