"""The semantic corpus (PRD section 5.6; ADR-0071): generated from the live catalogue code.

Parameter definitions, units and QC meanings, aggregation units, operations, presentations,
limits, region records with hand-written aliases, help texts and the curated examples. Numeric
observations are never embedded. Every document has a stable key and a content hash, so the
seed re-embeds only what changed.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..query.limits import QueryLimits
from ..query.plan import (
    DEPTH_BIN_SIZES,
    GROUP_KEYS,
    METRICS,
    PLAN_SCHEMA,
    PRESENTATIONS,
    QC_POLICIES,
    VARIABLES,
)
from ..query.policy import AGGREGATION_UNITS, POLICIES, POLICY_VERSION
from ..query.regions import load_regions
from ..query.sanitize import unit_for

CORPUS_VERSION = "corpus-v1"
EXAMPLES_SCHEMA = "nl-examples-v1"
ALIASES = Path(__file__).with_name("aliases.json")
EXAMPLES = Path(__file__).with_name("examples.json")
DOC_TYPES = (
    "parameter",
    "qc_policy",
    "aggregation_unit",
    "operation",
    "presentation",
    "limit",
    "region",
    "region_alias",
    "example",
    "help",
)
CONTEXT_TYPES = tuple(kind for kind in DOC_TYPES if kind != "example")

VARIABLE_DESCRIPTIONS = {
    "pressure": "Sea pressure in decibars, the vertical coordinate of a profile; 1 dbar is close "
    "to 1 metre of depth. Phrases: depth, deep, shallow, upper layer, surface, metres.",
    "temperature": "In-situ sea water temperature on the ITS-90 scale in degrees Celsius. "
    "Phrases: temp, warm, cold, heat, thermal, sea surface temperature (SST, the upper few "
    "decibars).",
    "salinity": "Practical salinity on the PSS-78 scale, dimensionless (often written PSU). "
    "Phrases: salt, salty, fresh, haline, salt level, salt content.",
}
QC_FLAGS = (
    "Argo quality-control flags per value: 1 good, 2 probably good, 3 probably bad (correctable), "
    "4 bad, 5 value changed, 8 estimated or interpolated, 9 missing. Data modes: R real-time "
    "(original values only), A real-time adjusted, D delayed-mode (adjusted values reviewed by "
    "the data centre)."
)
PRESENTATION_TEXT = {
    "table": "A table of rows; the default for aggregates and profile lists.",
    "line_chart": "A line chart of an aggregate over time; needs the aggregate operation with a "
    "month or day group key. Phrases: time series, trend, over time, monthly, daily, evolution.",
    "scatter": "A scatter plot of aggregate rows; needs the aggregate operation.",
    "profile_plot": "Temperature and salinity against pressure for a bounded set of profiles; "
    "needs the profiles operation. Phrases: vertical profile, against depth, versus pressure.",
    "ts_diagram": "A temperature-salinity diagram of a bounded set of profiles; needs the "
    "profiles operation and both temperature and salinity (pressure is included). Phrases: T-S "
    "diagram, TS plot, water masses.",
    "histogram": "A histogram of one value per profile (the aggregate with the profile group "
    "key); optional bins. Phrases: distribution, histogram, spread of values.",
    "map": "Profile or nearest-float positions on a map; needs the profiles or nearest "
    "operation. Phrases: map, where, locations, positions.",
}
HELP_TEXTS = {
    "scope": "FloatChat answers questions about Argo core observations: temperature, salinity "
    "and pressure profiles in the Indian Ocean. It lists profiles, aggregates values by month, "
    "day, profile, float, depth bin or region, finds the nearest floats to a point and draws "
    "time series, histograms, profile plots, T-S diagrams and maps. It does not forecast "
    "(Stage 6), export files (Stage 5) or serve biogeochemical variables (oxygen, chlorophyll, "
    "nitrate, pH; deferred).",
    "conventions": "Times are UTC; a time range has an inclusive start and an exclusive end "
    "(January 2025 is 2025-01-01T00:00:00Z to 2025-02-01T00:00:00Z). Longitudes are degrees "
    "east in -180..180; a bounding box whose west is greater than its east crosses the "
    "antimeridian. Depths are pressure in decibars; metres are treated as decibars. A request "
    "needs a time range and an area; when either is missing FloatChat asks instead of guessing.",
    "defaults": "When the question names no variable, temperature and salinity are used. The "
    "QC policy defaults to science_ready. Aggregates default to one value per profile; 'per "
    "measurement' or 'all levels' switches to measurement. Profile lists default to 100 rows; "
    "profile plots and T-S diagrams to 20 profiles. Nearest-float searches default to 5 floats "
    "within 500 km. An aggregate over more than one month needs a month, day or profile key. "
    "Requests longer than the time-span limit run as historical jobs (Stage 5) and are not "
    "answered in chat.",
}


@dataclass(frozen=True)
class Document:
    doc_type: str
    key: str
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_sha256(self) -> str:
        payload = json.dumps(
            [self.doc_type, self.key, self.title, self.text, self.metadata],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def identifier(self) -> str:
        return f"{self.doc_type}:{self.key}"

    @property
    def embedding_text(self) -> str:
        return f"{self.title}\n{self.text}"

    def context_line(self) -> str:
        """One delimited line for the model context: id, title, text (ADR-0073)."""
        return f"[{self.identifier}] {self.title}: {self.text}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "doc_type": self.doc_type,
            "key": self.key,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
            "content_sha256": self.content_sha256,
        }


def load_aliases(path: Path = ALIASES) -> dict[str, list[str]]:
    document = json.loads(path.read_text())
    if document.get("schema") != "region-aliases-v1":
        raise ValueError("unsupported alias fixture")
    return {
        name: [str(alias) for alias in aliases] for name, aliases in document["regions"].items()
    }


def load_examples(path: Path = EXAMPLES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    document = json.loads(path.read_text())
    if document.get("schema") != EXAMPLES_SCHEMA:
        raise ValueError("unsupported examples fixture")
    return [dict(item) for item in document["items"]]


def _parameter_documents() -> list[Document]:
    documents = []
    for variable in VARIABLES:
        unit = unit_for(variable)
        documents.append(
            Document(
                "parameter",
                variable,
                f"{variable} ({unit})",
                VARIABLE_DESCRIPTIONS[variable]
                + f" Plan variable name: {variable}. Unit: {unit}. Stored columns: {variable}, "
                f"{variable}_adjusted, {variable}_qc, {variable}_adjusted_qc, {variable}_error, "
                f"{variable}_data_mode.",
                {"variable": variable, "unit": unit},
            )
        )
    documents.append(Document("qc_policy", "flags", "QC flags and data modes", QC_FLAGS))
    for policy in QC_POLICIES:
        documents.append(
            Document(
                "qc_policy",
                policy,
                f"qc_policy {policy} ({POLICY_VERSION})",
                POLICIES[policy]
                + {
                    "science_ready": " Phrases: quality-controlled, good data, science quality, "
                    "adjusted, delayed-mode, default.",
                    "mode_selected": " Phrases: regardless of QC, ignore the flags, as delivered, "
                    "including flagged values, any QC.",
                    "raw": " Phrases: raw, unfiltered, every stored column; only with the "
                    "profiles operation.",
                }[policy],
                {"policy": policy, "version": POLICY_VERSION},
            )
        )
    for name, text in AGGREGATION_UNITS.items():
        documents.append(
            Document(
                "aggregation_unit",
                name,
                f"aggregation unit {name}",
                text
                + (
                    " Phrases: per profile, each profile, profile means (the default)."
                    if name == "profile"
                    else " Phrases: per measurement, every level, all levels, each reading."
                ),
                {"unit": name},
            )
        )
    return documents


def _operation_documents(limits: QueryLimits) -> list[Document]:
    return [
        Document(
            "operation",
            "profiles",
            "operation profiles",
            "Lists profile headers (platform, cycle, time, position, level count) newest "
            f"first; needs limit (1..{limits.page_size}, default {limits.default_page_size}). "
            "Phrases: list, show, which profiles, how were the profiles, give me the profiles.",
            {"kind": "profiles"},
        ),
        Document(
            "operation",
            "aggregate",
            "operation aggregate",
            f"Metrics {', '.join(METRICS)} over the selected values, grouped by any of "
            f"{', '.join(GROUP_KEYS)}; depth_bin needs depth_bin_size in {DEPTH_BIN_SIZES}; "
            "unit profile (one value per profile, then metrics across profiles; count counts "
            "profiles) or measurement (metrics over levels; count counts levels). Phrases: "
            "mean, average, minimum, maximum, median, standard deviation, how many, count, "
            "monthly, daily, per float, by depth, by region.",
            {"kind": "aggregate"},
        ),
        Document(
            "operation",
            "nearest",
            "operation nearest",
            "The k nearest profiles to a point (longitude, latitude) within radius_km "
            f"(at most {limits.nearest_radius_km:.0f} km, k at most {limits.nearest_k}); table or "
            "map. Phrases: nearest float, closest float, near this position.",
            {"kind": "nearest"},
        ),
    ]


def _presentation_documents() -> list[Document]:
    return [
        Document(
            "presentation", kind, f"presentation {kind}", PRESENTATION_TEXT[kind], {"kind": kind}
        )
        for kind in PRESENTATIONS
    ]


def _limit_documents(limits: QueryLimits) -> list[Document]:
    public = limits.public()
    return [
        Document(
            "limit",
            "query",
            "query limits",
            f"time span at most {public['time_span_days']} days per request; page size "
            f"{public['page_size']}; nearest radius at most {public['nearest_radius_km']:.0f} km "
            f"and k at most {public['nearest_k']}; at most {public['chart_series']} profiles per "
            f"profile chart; histogram bins at most {public['histogram_bins']}.",
            {"limits": public},
        )
    ]


def _region_documents(aliases: dict[str, list[str]]) -> list[Document]:
    documents = []
    for record in load_regions():
        bbox = record.bbox
        documents.append(
            Document(
                "region",
                record.name,
                f"named region {record.name}",
                f"{record.kind} region from {record.source}; bounding box west {bbox[0]:.1f}, "
                f"south {bbox[1]:.1f}, east {bbox[2]:.1f}, north {bbox[3]:.1f} degrees; area "
                f"{record.area_km2:,.0f} km2. {record.note}".strip(),
                {"region": record.name, "version": record.version, "kind": record.kind},
            )
        )
        names = aliases.get(record.name, [])
        documents.append(
            Document(
                "region_alias",
                record.name,
                f"aliases of {record.name}",
                f"Phrases that mean the named region {record.name}: "
                + (", ".join(names) if names else "(none)")
                + '. Plan geography: {"kind": "named_region", "value": "'
                + record.name
                + '"}.',
                {"region": record.name, "aliases": names},
            )
        )
    return documents


def _example_documents(examples: Sequence[dict[str, Any]]) -> list[Document]:
    documents = []
    for item in examples:
        answer = item["answer"]
        documents.append(
            Document(
                "example",
                str(item["id"]),
                str(item["question"]),
                "Answer: " + json.dumps(answer, sort_keys=True, separators=(",", ":")),
                {"question": item["question"], "answer": answer},
            )
        )
    return documents


def _help_documents() -> list[Document]:
    return [Document("help", key, f"help {key}", text, {}) for key, text in HELP_TEXTS.items()] + [
        Document(
            "help",
            "plan_schema",
            f"plan schema {PLAN_SCHEMA}",
            "A plan has dataset core, time_range {start, end}, geography (named_region value | "
            "bbox west south east north | point_radius longitude latitude radius_km), optional "
            "depth_dbar {min, max}, variables, qc_policy, operation and presentation.",
            {"plan_schema": PLAN_SCHEMA},
        )
    ]


def build_corpus(
    *,
    limits: QueryLimits | None = None,
    aliases: dict[str, list[str]] | None = None,
    examples: Sequence[dict[str, Any]] | None = None,
) -> list[Document]:
    limits = limits or QueryLimits()
    aliases = load_aliases() if aliases is None else aliases
    examples = load_examples() if examples is None else examples
    documents = (
        _parameter_documents()
        + _operation_documents(limits)
        + _presentation_documents()
        + _limit_documents(limits)
        + _region_documents(aliases)
        + _help_documents()
        + _example_documents(examples)
    )
    keys = [document.identifier for document in documents]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate semantic document")
    return documents


def catalogue_summary(limits: QueryLimits | None = None) -> str:
    """The schema-only context (ADR-0074): what every ablation sees, without retrieval."""
    limits = limits or QueryLimits()
    regions = ", ".join(record.name for record in load_regions())
    return (
        f"Plan schema {PLAN_SCHEMA}. Variables: {', '.join(VARIABLES)}. QC policies: "
        f"{', '.join(QC_POLICIES)} (default science_ready). Operations: profiles (limit), "
        f"aggregate (group_by {', '.join(GROUP_KEYS)}; metrics {', '.join(METRICS)}; unit "
        f"profile|measurement; depth_bin_size {DEPTH_BIN_SIZES}), nearest (longitude, latitude, "
        f"radius_km, k). Presentations: {', '.join(PRESENTATIONS)}. Named regions: {regions}. "
        f"Limits: time span {limits.time_span_days} days, page size {limits.page_size}, nearest "
        f"radius {limits.nearest_radius_km:.0f} km, k {limits.nearest_k}, chart series "
        f"{limits.chart_series}."
    )
