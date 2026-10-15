"""The NL harness (ADR-0074): scoring on hand-made outcomes and a small offline run."""

from pathlib import Path

from floatchat_core.chat.pipeline import PlanOutcome
from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.provider import Usage
from floatchat_core.query.plan import validate_plan

from eval.nl.harness import (
    FIELDS,
    HarnessEngine,
    ItemResult,
    RunConfig,
    canonical_plan,
    render_report,
    run,
    score,
    summarize,
)

GOLD_PLAN = {
    "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
    "geography": {"kind": "named_region", "value": "Arabian Sea"},
    "variables": ["temperature"],
    "qc_policy": "science_ready",
    "operation": {"kind": "aggregate", "group_by": [], "metrics": ["mean"], "unit": "profile"},
    "presentation": {"kind": "table"},
}


def item(kind="plan", **overrides):
    base = {
        "id": "t-1",
        "split": "test",
        "category": "date_phrases",
        "question": "q",
        "ambiguous": kind == "clarify",
        "executable": kind == "plan",
        "gold": {"kind": kind, "plan": GOLD_PLAN, "missing": ["time_range"]},
    }
    base.update(overrides)
    return base


def outcome(kind="plan", plan=GOLD_PLAN, missing=("time_range",), validation=()):
    result = PlanOutcome("query", kind)
    if kind == "plan":
        result.plan = validate_plan(dict(plan))
        result.document = result.plan.canonical()
    if kind == "clarify":
        result.clarification = {"missing": list(missing), "question": "?"}
    result.validation = list(validation)
    result.usage = Usage(100, 20, 0)
    result.latency_ms = 12.0
    return result


def test_scoring_exact_field_and_failure_types():
    engine = HarnessEngine("2025-04-01T00:00:00Z", None)
    exact = score(item(), outcome(), None, engine)
    assert exact.kind_match and exact.exact_match and all(exact.fields.values())
    assert exact.failure is None and exact.result_match is None
    wrong = dict(GOLD_PLAN, geography={"kind": "named_region", "value": "Bay of Bengal"})
    geography = score(item(), outcome(plan=wrong), None, engine)
    assert geography.exact_match is False and geography.failure == "wrong_geography"
    assert geography.fields["time_range"] and not geography.fields["geography"]
    asked = score(item(), outcome("clarify"), None, engine)
    assert asked.failure == "unnecessary_clarification" and not asked.clarification_appropriate
    invalid = score(
        item(),
        outcome(
            "clarify",
            validation=[{"field": "variables", "code": "unknown_variable", "message": "x"}],
        ),
        None,
        engine,
    )
    assert invalid.failure == "invalid_plan"
    silent = score(item("clarify"), outcome(), None, engine)
    assert silent.failure == "missing_clarification" and silent.missing_match is False
    right_question = score(item("clarify"), outcome("clarify"), None, engine)
    assert (
        right_question.kind_match
        and right_question.missing_match
        and right_question.failure is None
    )
    other_field = score(item("clarify"), outcome("clarify", missing=("geography",)), None, engine)
    assert other_field.kind_match and other_field.missing_match is False
    unsupported = score(item("unsupported"), outcome(), None, engine)
    assert unsupported.failure == "unsupported_mismatch"
    failed = score(item(), None, "llm_unavailable", engine)
    assert failed.failure == "provider_error" and failed.fields == {name: False for name in FIELDS}


def test_summary_rates_and_report_header(tmp_path: Path):
    engine = HarnessEngine("2025-04-01T00:00:00Z", None)
    results = [
        score(item(), outcome(), None, engine),
        score(item(id="t-2", ambiguous=False), outcome("clarify"), None, engine),
        score(item("unsupported", id="t-3"), outcome("unsupported"), None, engine),
    ]
    summary = summarize(results)
    assert summary["items"] == 3 and summary["plan_items"] == 2
    assert summary["plan_exact_match"] == 0.5 and summary["kind_accuracy"] == round(2 / 3, 4)
    assert summary["result_accuracy"] is None and summary["failures"] == {
        "unnecessary_clarification": 1
    }
    assert isinstance(results[0], ItemResult)
    assert canonical_plan({"nonsense": True}) is None


def test_small_offline_run_writes_a_labelled_report(tmp_path: Path):
    config = RunConfig(
        split="dev",
        ablations=("schema_only", "rag_examples"),
        providers=("offline",),
        api_url=None,
        limit=6,
        seed=7,
        out_dir=tmp_path,
        date="2026-01-01",
    )
    document = run(config, LlmSettings(provider="offline"))
    assert document["items"] == 6 and len(document["runs"]) == 2
    assert document["prompt_versions"] == {"planner": "planner-v2", "narrator": "narrator-v1"}
    assert len(document["commit"]) in (7, 40) or document["commit"] == "unknown"
    report = (tmp_path / "eval_nl_2026-01-01.md").read_text()
    assert "Not an LLM result" in report and "offline-rules-v1" in report
    assert "skipped (no `--api-url`" in report and "needs human review" in report
    assert "| offline | `offline-rules-v1` | schema_only |" in report
    assert (tmp_path / "eval_nl_2026-01-01.json").exists()
    rendered = render_report(document)
    assert rendered.startswith("# NL-to-plan evaluation, 2026-01-01")
    for run_record in document["runs"]:
        summary = run_record["summary"]
        assert summary["result_accuracy"] is None
        assert 0 <= (summary["plan_exact_match"] or 0) <= 1
