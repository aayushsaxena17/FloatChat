"""The semantic corpus, the hashed embedding and the in-memory retriever (ADR-0071)."""

import json
from pathlib import Path

import pytest
from floatchat_core.chat.schema import to_plan_document
from floatchat_core.query.plan import validate_plan
from floatchat_core.query.regions import load_regions
from floatchat_core.rag.corpus import (
    CONTEXT_TYPES,
    DOC_TYPES,
    catalogue_summary,
    load_aliases,
    load_examples,
)
from floatchat_core.rag.embeddings import cosine, hash_embed

ROOT = Path(__file__).resolve().parents[2]


def test_corpus_covers_every_document_type_with_unique_ids(corpus):
    documents, vectors = corpus
    types = {document.doc_type for document in documents}
    assert types == set(DOC_TYPES)
    identifiers = [document.identifier for document in documents]
    assert len(set(identifiers)) == len(identifiers)
    assert all(len(vector) == 768 for vector in vectors)
    assert "example" not in CONTEXT_TYPES


def test_every_region_has_aliases_and_an_alias_document(corpus):
    documents, _ = corpus
    aliases = load_aliases()
    for record in load_regions():
        assert len(aliases[record.name]) >= 3, record.name
        alias_document = next(
            document
            for document in documents
            if document.doc_type == "region_alias" and document.key == record.name
        )
        assert alias_document.metadata["region"] == record.name
        assert set(alias_document.metadata["aliases"]) == set(aliases[record.name])
    assert set(aliases) == {record.name for record in load_regions()}


def test_examples_are_curated_valid_and_disjoint_from_the_test_split():
    examples = load_examples()
    assert len(examples) >= 30
    identifiers = [item["id"] for item in examples]
    assert len(set(identifiers)) == len(identifiers)
    kinds = {item["answer"]["kind"] for item in examples}
    assert kinds == {"plan", "clarify", "unsupported"}
    for item in examples:
        if item["answer"]["kind"] == "plan":
            validate_plan(to_plan_document(item["answer"]["plan"]))
    test_split = ROOT / "eval/golden/test.json"
    if test_split.exists():
        held_out = {
            " ".join(entry["question"].lower().split())
            for entry in json.loads(test_split.read_text())["items"]
        }
        leaked = [
            item["id"]
            for item in examples
            if " ".join(item["question"].lower().split()) in held_out
        ]
        assert leaked == []


def test_hash_embedding_is_deterministic_unit_length_and_lexical():
    first = hash_embed("mean temperature in the Arabian Sea")
    second = hash_embed("mean temperature in the Arabian Sea")
    assert first == second and len(first) == 768
    assert sum(value * value for value in first) == pytest.approx(1.0)
    related = hash_embed("average temperature of the arabian sea")
    unrelated = hash_embed("export parquet files next year")
    assert cosine(first, related) > cosine(first, unrelated)
    assert hash_embed("") == [0.0] * 768


def test_content_hash_changes_with_text(corpus):
    documents, _ = corpus
    document = documents[0]
    changed = type(document)(
        document.doc_type, document.key, document.title, document.text + " more", document.metadata
    )
    assert changed.content_sha256 != document.content_sha256
    assert len(document.content_sha256) == 64


def test_memory_retriever_ranks_the_matching_alias_document_first(retriever):
    vector = hash_embed("salinity in BoB (Bengal bay) last month")
    hits = retriever.search(vector, top_k=3, doc_types=["region_alias"])
    assert hits[0].document.key == "Bay of Bengal"
    assert all(hit.document.doc_type == "region_alias" for hit in hits)
    assert len(hits) == 3
    everything = retriever.search(vector, top_k=5)
    assert len(everything) == 5
    assert everything == sorted(
        everything, key=lambda hit: (-round(hit.score, 9), hit.document.doc_type, hit.document.key)
    )
    as_dict = everything[0].as_dict()
    assert set(as_dict) == {"id", "doc_type", "title", "score"}


def test_catalogue_summary_names_regions_variables_and_limits():
    summary = catalogue_summary()
    for record in load_regions():
        assert record.name in summary
    assert "temperature" in summary and "science_ready" in summary and "366" in summary
