"""``make eval-nl``: the golden benchmark over every configured provider and ablation.

    uv run --all-packages --frozen python -m eval.nl.harness --split test --ablations all
    ... --providers offline,gemini --api-url http://127.0.0.1:8000   # result accuracy too

Metrics (PRD section 30.3): plan exact match, field-level accuracy, result accuracy (through
``POST /v1/query`` when ``--api-url`` is given, otherwise reported as skipped), clarification
appropriateness, latency p50/p95, tokens per query, and a failure taxonomy. The report records
the commit, the provider and model, the prompt versions, the embedding model, the seed, the split
sizes and the reference time. A run with the offline provider is a harness smoke test, not an LLM
result, and the report header says so (ADR-0074).
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from floatchat_core.chat.pipeline import ChatService, PlanOutcome
from floatchat_core.chat.prompts import NARRATOR_VERSION, PLANNER_VERSION
from floatchat_core.chat.schema import to_plan_document
from floatchat_core.chat.store import MemoryStore
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.factory import build_provider
from floatchat_core.llm.ledger import MemoryLedger
from floatchat_core.query.errors import QueryError
from floatchat_core.query.plan import validate_plan
from floatchat_core.query.regions import load_regions
from floatchat_core.rag.corpus import CORPUS_VERSION, build_corpus
from floatchat_core.rag.retriever import MemoryRetriever

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "eval" / "golden"
REPORTS = ROOT / "reports"
SCHEMA = "golden-nl-v1"
FIELDS = (
    "time_range",
    "geography",
    "depth_dbar",
    "variables",
    "qc_policy",
    "operation",
    "presentation",
)
ABLATIONS = ("schema_only", "rag", "rag_examples")
FAILURE_TYPES = (
    "wrong_time_range",
    "wrong_geography",
    "wrong_depth",
    "wrong_variables",
    "wrong_qc_policy",
    "wrong_operation",
    "wrong_presentation",
    "missing_clarification",
    "unnecessary_clarification",
    "unsupported_mismatch",
    "invalid_plan",
    "provider_error",
)


# ----- items -------------------------------------------------------------------------------------


def load_split(name: str) -> dict[str, Any]:
    document = json.loads((GOLDEN / f"{name}.json").read_text())
    if document.get("schema") != SCHEMA:
        raise ValueError(f"unsupported golden schema in {name}")
    return document


def load_items(split: str) -> tuple[list[dict[str, Any]], str]:
    names = ["dev", "test"] if split == "all" else [split]
    items: list[dict[str, Any]] = []
    reference = None
    for name in names:
        document = load_split(name)
        reference = reference or document["reference_time"]
        for item in document["items"]:
            items.append({**item, "split": name})
    assert reference is not None
    return items, reference


def canonical_plan(flat: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return validate_plan(to_plan_document(flat)).canonical()
    except QueryError:
        return None


# ----- the engine stand-in -----------------------------------------------------------------------


class HarnessEngine:
    """Only what ``ChatService.plan`` needs; ``query`` goes through the API when configured."""

    def __init__(self, reference_time: str, api_url: str | None) -> None:
        self.reference_time = reference_time
        self.api_url = api_url.rstrip("/") if api_url else None
        self._client = httpx.Client(timeout=60.0) if api_url else None
        self.fingerprints: dict[str, str | None] = {}

    def parameters(self) -> dict[str, Any]:
        return {"geography": {"named_region": [record.public() for record in load_regions()]}}

    def environment_info(self) -> dict[str, Any]:
        return {"reference_time": self.reference_time, "postgresql_window": {}}

    def query(self, payload: Any) -> dict[str, Any]:
        raise QueryError("service_unavailable")

    def fingerprint(self, plan: dict[str, Any]) -> str | None:
        """``provenance.result_sha256`` of the executed plan, memoised by the plan hash."""
        if self._client is None or self.api_url is None:
            return None
        document = {key: value for key, value in plan.items() if key != "plan_schema"}
        key = json.dumps(document, sort_keys=True)
        if key in self.fingerprints:
            return self.fingerprints[key]
        try:
            response = self._client.post(f"{self.api_url}/v1/query", json=document)
            if response.status_code == 200:
                value: str | None = response.json()["provenance"]["result_sha256"]
            else:
                value = "error:" + str(response.json().get("error", {}).get("code", "unknown"))
        except (httpx.HTTPError, ValueError, KeyError):
            value = "error:transport"
        self.fingerprints[key] = value
        return value


# ----- scoring -----------------------------------------------------------------------------------


@dataclass
class ItemResult:
    id: str
    split: str
    category: str
    question: str
    gold_kind: str
    predicted_kind: str
    kind_match: bool
    exact_match: bool | None
    fields: dict[str, bool] = field(default_factory=dict)
    clarification_appropriate: bool = True
    missing_match: bool | None = None
    result_match: bool | None = None
    failure: str | None = None
    latency_ms: float = 0.0
    tokens: int = 0
    predicted_plan: dict[str, Any] | None = None
    gold_plan: dict[str, Any] | None = None
    predicted_text: str | None = None
    validation: list[dict[str, str]] = field(default_factory=list)


def score(
    item: dict[str, Any], outcome: PlanOutcome | None, error: str | None, engine: HarnessEngine
) -> ItemResult:
    gold = item["gold"]
    gold_plan = canonical_plan(gold["plan"]) if gold["kind"] == "plan" else None
    result = ItemResult(
        id=item["id"],
        split=item["split"],
        category=item["category"],
        question=item["question"],
        gold_kind=gold["kind"],
        predicted_kind="error" if outcome is None else outcome.kind,
        kind_match=False,
        exact_match=None if gold["kind"] != "plan" else False,
        gold_plan=gold_plan,
    )
    if outcome is None:
        result.failure = "provider_error"
        result.predicted_text = error
        result.clarification_appropriate = not item["ambiguous"]
        if gold["kind"] == "plan":
            result.fields = {name: False for name in FIELDS}
        return result
    result.latency_ms = outcome.latency_ms
    result.tokens = outcome.usage.total
    result.validation = list(outcome.validation)
    predicted_plan = outcome.document
    result.predicted_plan = predicted_plan
    if outcome.kind == "clarify" and outcome.clarification is not None:
        result.predicted_text = outcome.clarification["question"]
    elif outcome.kind == "unsupported":
        result.predicted_text = outcome.reason
    result.kind_match = outcome.kind == gold["kind"]
    asked = outcome.kind == "clarify"
    result.clarification_appropriate = asked == bool(item["ambiguous"])
    if gold["kind"] == "clarify":
        if asked and outcome.clarification is not None:
            result.missing_match = set(outcome.clarification["missing"]) == set(gold["missing"])
        else:
            result.missing_match = False
            result.failure = "missing_clarification"
        return result
    if gold["kind"] == "unsupported":
        if not result.kind_match:
            result.failure = "unnecessary_clarification" if asked else "unsupported_mismatch"
        return result
    # gold is a plan
    assert gold_plan is not None
    if predicted_plan is None or outcome.kind != "plan":
        result.fields = {name: False for name in FIELDS}
        if asked:
            result.failure = "invalid_plan" if outcome.validation else "unnecessary_clarification"
        else:
            result.failure = "unsupported_mismatch"
        return result
    result.fields = {name: predicted_plan.get(name) == gold_plan.get(name) for name in FIELDS}
    result.exact_match = all(result.fields.values())
    if not result.exact_match:
        wrong = next(name for name in FIELDS if not result.fields[name])
        result.failure = "wrong_" + wrong
    if item.get("executable") and engine.api_url:
        gold_print = engine.fingerprint(gold_plan)
        if result.exact_match:
            result.result_match = gold_print is not None and not gold_print.startswith("error:")
        else:
            predicted_print = engine.fingerprint(predicted_plan)
            result.result_match = (
                gold_print is not None
                and predicted_print == gold_print
                and not gold_print.startswith("error:")
            )
    return result


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


def summarize(results: Sequence[ItemResult]) -> dict[str, Any]:
    plans = [result for result in results if result.gold_kind == "plan"]
    executed = [result for result in results if result.result_match is not None]
    by_category: dict[str, list[ItemResult]] = defaultdict(list)
    for result in results:
        by_category[result.category].append(result)
    failures = Counter(result.failure for result in results if result.failure)
    return {
        "items": len(results),
        "plan_items": len(plans),
        "kind_accuracy": _rate([result.kind_match for result in results]),
        "plan_exact_match": _rate([bool(result.exact_match) for result in plans]),
        "field_accuracy": {
            name: _rate([result.fields.get(name, False) for result in plans]) for name in FIELDS
        },
        "clarification_appropriateness": _rate(
            [result.clarification_appropriate for result in results]
        ),
        "result_accuracy": _rate([bool(result.result_match) for result in executed])
        if executed
        else None,
        "result_items": len(executed),
        "latency_p50_ms": round(percentile([result.latency_ms for result in results], 0.5), 1),
        "latency_p95_ms": round(percentile([result.latency_ms for result in results], 0.95), 1),
        "tokens_per_query": round(statistics.mean([result.tokens for result in results]), 1)
        if results
        else 0.0,
        "by_category": {
            name: {
                "items": len(rows),
                "kind_accuracy": _rate([row.kind_match for row in rows]),
                "plan_exact_match": _rate(
                    [bool(row.exact_match) for row in rows if row.gold_kind == "plan"]
                ),
            }
            for name, rows in sorted(by_category.items())
        },
        "failures": dict(failures.most_common()),
    }


def _rate(values: Sequence[bool]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value) / len(values), 4)


# ----- running -----------------------------------------------------------------------------------


@dataclass
class RunConfig:
    split: str
    ablations: tuple[str, ...]
    providers: tuple[str, ...]
    api_url: str | None
    limit: int | None
    seed: int
    out_dir: Path
    write_report: bool = True
    date: str = ""


def configured_providers(settings: LlmSettings, requested: str) -> list[str]:
    if requested != "auto":
        return [name.strip() for name in requested.split(",") if name.strip()]
    names = ["offline"]
    for name in ("gemini", "openai"):
        if settings.key_for(name) is not None:
            names.append(name)
    return names


def run(config: RunConfig, settings: LlmSettings | None = None) -> dict[str, Any]:
    settings = settings or LlmSettings()
    items, reference = load_items(config.split)
    if config.limit:
        items = items[: config.limit]
    documents = build_corpus()
    engine = HarnessEngine(reference, config.api_url)
    runs: list[dict[str, Any]] = []
    for provider_name in config.providers:
        ledger = MemoryLedger()
        provider = build_provider(settings, ledger, provider=provider_name)
        vectors = provider.embed([document.embedding_text for document in documents], "document")
        retriever = MemoryRetriever(documents, vectors.vectors, provider.embedding_model)
        for ablation in config.ablations:
            service = ChatService(
                engine,
                provider,
                retriever,
                MemoryStore(),
                mode=ablation,  # type: ignore[arg-type]
                narrate_with_model=False,
                retrieval_top_k=settings.retrieval_top_k,
                planner_max_output_tokens=settings.planner_max_output_tokens,
            )
            results: list[ItemResult] = []
            started = time.monotonic()
            for item in items:
                outcome: PlanOutcome | None
                error: str | None = None
                try:
                    outcome = service.plan(item["question"], reference_time=reference)
                except QueryError as failure:
                    outcome, error = None, failure.code
                results.append(score(item, outcome, error, engine))
            runs.append(
                {
                    "provider": provider.name,
                    "model": provider.model,
                    "embedding_model": provider.embedding_model,
                    "ablation": ablation,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "ledger_usd": round(sum(call.estimated_usd for _d, call in ledger.calls), 4),
                    "summary": summarize(results),
                    "results": [asdict(result) for result in results],
                }
            )
    document = {
        "schema": "eval-nl-run-v1",
        "date": config.date or datetime.now(UTC).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": commit_hash(),
        "split": config.split,
        "items": len(items),
        "split_sizes": dict(Counter(item["split"] for item in items)),
        "reference_time": reference,
        "prompt_versions": {"planner": PLANNER_VERSION, "narrator": NARRATOR_VERSION},
        "corpus_version": CORPUS_VERSION,
        "corpus_documents": len(documents),
        "seed": config.seed,
        "api_url": config.api_url,
        "runs": runs,
    }
    if config.write_report:
        config.out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"eval_nl_{document['date']}"
        (config.out_dir / f"{stem}.json").write_text(json.dumps(document, indent=1) + "\n")
        (config.out_dir / f"{stem}.md").write_text(render_report(document))
        document["report_path"] = str(config.out_dir / f"{stem}.md")
    return document


def commit_hash() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ----- report ------------------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def render_report(document: dict[str, Any]) -> str:
    runs = document["runs"]
    offline_only = all(run["provider"] == "offline" for run in runs)
    lines = [
        f"# NL-to-plan evaluation, {document['date']}",
        "",
        f"- Commit: `{document['commit']}`",
        f"- Generated: {document['generated_at']}",
        f"- Split: {document['split']} ({document['items']} items; "
        + ", ".join(f"{name} {count}" for name, count in sorted(document["split_sizes"].items()))
        + ")",
        f"- Reference time: {document['reference_time']}",
        f"- Prompt versions: planner `{document['prompt_versions']['planner']}`, narrator "
        f"`{document['prompt_versions']['narrator']}`; corpus `{document['corpus_version']}` "
        f"({document['corpus_documents']} documents)",
        f"- Seed: {document['seed']}",
        "- Providers and models: "
        + "; ".join(
            sorted(
                {
                    f"{run['provider']} `{run['model']}` (embedding `{run['embedding_model']}`)"
                    for run in runs
                }
            )
        ),
        "- Result accuracy: "
        + (
            f"executed through `{document['api_url']}`"
            if document.get("api_url")
            else "skipped (no `--api-url`; plans were not executed)"
        ),
        "",
    ]
    if offline_only:
        lines += [
            "> **Not an LLM result.** Every run below used the `offline` provider "
            "(`offline-rules-v1`, a deterministic rule-based planner, with `hash-embed-v1` "
            "embeddings). No Gemini or other model key existed on the host when this report was "
            "generated. These numbers are a harness smoke test and the no-model floor of the "
            "ablation; the Stage 4 research number (RQ1) requires a run with a model key.",
            "",
        ]
    lines += [
        "> Gold plans were drafted by the builder and carry `review: needs human review`; numbers "
        "are provisional until the owner reviews the benchmark (PRD §30.2).",
        "",
        "## Summary",
        "",
        "| Provider | Model | Ablation | Kind acc. | Plan exact | Clarif. appr. | Result acc. "
        "| p50 ms | p95 ms | Tokens/q | USD |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        summary = run["summary"]
        lines.append(
            f"| {run['provider']} | `{run['model']}` | {run['ablation']} | "
            f"{_pct(summary['kind_accuracy'])} | {_pct(summary['plan_exact_match'])} | "
            f"{_pct(summary['clarification_appropriateness'])} | "
            f"{_pct(summary['result_accuracy'])} ({summary['result_items']}) | "
            f"{summary['latency_p50_ms']} | {summary['latency_p95_ms']} | "
            f"{summary['tokens_per_query']} | {run['ledger_usd']} |"
        )
    lines += ["", "## Field-level accuracy (plan items)", ""]
    header = "| Provider | Ablation | " + " | ".join(FIELDS) + " |"
    lines += [header, "|" + "---|" * (len(FIELDS) + 2)]
    for run in runs:
        fields = run["summary"]["field_accuracy"]
        lines.append(
            f"| {run['provider']} | {run['ablation']} | "
            + " | ".join(_pct(fields[name]) for name in FIELDS)
            + " |"
        )
    for run in runs:
        summary = run["summary"]
        lines += [
            "",
            f"## {run['provider']} / {run['ablation']}: categories and failures",
            "",
            "| Category | Items | Kind acc. | Plan exact |",
            "|---|---|---|---|",
        ]
        for name, row in summary["by_category"].items():
            lines.append(
                f"| {name} | {row['items']} | {_pct(row['kind_accuracy'])} | "
                f"{_pct(row['plan_exact_match'])} |"
            )
        lines += ["", "Most common failure types (with one example each):", ""]
        examples: dict[str, dict[str, Any]] = {}
        for result in run["results"]:
            if result["failure"] and result["failure"] not in examples:
                examples[result["failure"]] = result
        if not summary["failures"]:
            lines.append("- none")
        for failure, count in list(summary["failures"].items())[:10]:
            example = examples[failure]
            predicted = (
                example["predicted_plan"] or example["predicted_text"] or example["predicted_kind"]
            )
            gold = example["gold_plan"] or example["gold_kind"]
            lines.append(
                f'- **{failure}** ({count}): `{example["id"]}` "{example["question"]}" -> '
                f"predicted `{_short(predicted)}`; gold `{_short(gold)}`"
            )
    lines += [
        "",
        "## Integrity",
        "",
        "- Prompts, the rule-based planner and retrieval were tuned on the development split only "
        "(ADR-0074); the held-out split is reported as is.",
        "- Plan exact match compares canonical `stage2-plan-v1` documents; field accuracy scores "
        "the "
        "seven plan fields separately; clarification appropriateness is `asked == ambiguous`.",
        "- Per-item results: the JSON sidecar next to this report.",
        "",
    ]
    return "\n".join(lines)


def _short(value: Any, limit: int = 160) -> str:
    text = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if not isinstance(value, str)
        else value
    )
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ----- cli ---------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--ablations", default="all", help="comma list or 'all'")
    parser.add_argument("--providers", default="auto", help="comma list or 'auto'")
    parser.add_argument("--api-url", default=os.environ.get("FLOATCHAT_API_URL"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default=str(REPORTS))
    parser.add_argument("--date", default=None)
    arguments = parser.parse_args(argv)
    settings = LlmSettings()
    ablations = (
        ABLATIONS
        if arguments.ablations == "all"
        else tuple(name.strip() for name in arguments.ablations.split(","))
    )
    for name in ablations:
        if name not in ABLATIONS:
            parser.error(f"unknown ablation {name}")
    providers = tuple(configured_providers(settings, arguments.providers))
    config = RunConfig(
        split=arguments.split,
        ablations=ablations,
        providers=providers,
        api_url=arguments.api_url,
        limit=arguments.limit,
        seed=arguments.seed,
        out_dir=Path(arguments.out),
        date=arguments.date or "",
    )
    document = run(config, settings)
    for item in document["runs"]:
        summary = item["summary"]
        print(
            json.dumps(
                {
                    "provider": item["provider"],
                    "model": item["model"],
                    "ablation": item["ablation"],
                    "kind_accuracy": summary["kind_accuracy"],
                    "plan_exact_match": summary["plan_exact_match"],
                    "clarification_appropriateness": summary["clarification_appropriateness"],
                    "result_accuracy": summary["result_accuracy"],
                }
            )
        )
    print(json.dumps({"report": document.get("report_path")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
