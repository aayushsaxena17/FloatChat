"""The golden benchmark (ADR-0074): schema, counts, categories, validity, no leakage."""

import json
from collections import Counter
from pathlib import Path

from floatchat_core.chat.schema import to_plan_document
from floatchat_core.query.geography import resolve_geography
from floatchat_core.query.plan import validate_plan
from floatchat_core.rag.corpus import load_examples

ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = {
    "date_phrases",
    "named_regions",
    "longitude_dateline",
    "nearest_float",
    "depth_filters",
    "original_vs_adjusted",
    "qc_selection",
    "aggregation_unit",
    "empty_sparse",
    "core_bgc_availability",
    "scope_injection",
}


def splits():
    return {
        name: json.loads((ROOT / "eval/golden" / f"{name}.json").read_text())
        for name in ("dev", "test")
    }


def test_sizes_schema_and_reference_time():
    documents = splits()
    assert all(document["schema"] == "golden-nl-v1" for document in documents.values())
    assert all(
        document["reference_time"] == "2025-04-01T00:00:00Z" for document in documents.values()
    )
    dev, test = len(documents["dev"]["items"]), len(documents["test"]["items"])
    assert dev + test >= 150
    assert 40 <= dev <= 70 and test >= 100


def test_every_item_is_well_formed_and_awaits_review():
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for name, document in splits().items():
        for item in document["items"]:
            assert item["id"].startswith(name + "-") and item["id"] not in seen_ids
            seen_ids.add(item["id"])
            question = " ".join(item["question"].lower().split())
            assert question not in seen_questions, item["id"]
            seen_questions.add(question)
            assert item["category"] in CATEGORIES
            assert item["review"] == "needs human review"
            assert isinstance(item["ambiguous"], bool) and isinstance(item["executable"], bool)
            gold = item["gold"]
            assert gold["kind"] in ("plan", "clarify", "unsupported")
            assert item["ambiguous"] == (gold["kind"] == "clarify")
            if gold["kind"] == "clarify":
                assert gold["missing"] and not item["executable"]
            if gold["kind"] == "unsupported":
                assert not item["executable"]


def test_every_gold_plan_passes_the_live_validator_and_region_fixture():
    for document in splits().values():
        for item in document["items"]:
            if item["gold"]["kind"] != "plan":
                continue
            plan = validate_plan(to_plan_document(item["gold"]["plan"]))
            resolve_geography(plan.geography)


def test_categories_are_all_covered_in_both_splits():
    for document in splits().values():
        counts = Counter(item["category"] for item in document["items"])
        assert set(counts) >= CATEGORIES - {"scope_injection"}, counts
    combined = Counter(
        item["category"] for document in splits().values() for item in document["items"]
    )
    assert all(combined[name] >= 10 for name in CATEGORIES - {"scope_injection"}), combined
    assert combined["scope_injection"] >= 5


def test_held_out_questions_are_not_in_the_curated_examples():
    held_out = {" ".join(item["question"].lower().split()) for item in splits()["test"]["items"]}
    for example in load_examples():
        assert " ".join(example["question"].lower().split()) not in held_out, example["id"]
