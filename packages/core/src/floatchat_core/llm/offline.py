"""The ``offline`` provider (ADR-0069, ADR-0070): ``offline-rules-v1`` and ``hash-embed-v1``.

A deterministic rule-based planner over the same context the model receives (the question,
the reference time, the catalogue summary, the retrieved documents). It exists so the tests,
the integration stack and the harness run without a key, and as the no-model floor of the
ablation. It is not an LLM and names itself wherever it answers. Its rules were tuned on the
development split only (ADR-0074).
"""

import calendar
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ..query.plan import MAX_DEPTH_DBAR
from ..rag.embeddings import hash_embed_many
from .config import OFFLINE_EMBEDDING_MODEL, OFFLINE_MODEL
from .provider import (
    EmbedResult,
    EmbedTask,
    StructuredRequest,
    StructuredResult,
    TextRequest,
    TextStream,
    Usage,
)

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if number}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if number})
MONTHS["sept"] = 9
MONTH_WORD = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
}
BGC_WORDS = (
    "oxygen",
    "chlorophyll",
    "nitrate",
    "ph ",
    "bgc",
    "biogeochem",
    "backscatter",
    "cdom",
    "irradiance",
    "doxy",
    "chla",
)
EXPORT_WORDS = ("export", "download", "csv", "parquet", "netcdf", " file")
FORECAST_WORDS = ("forecast", "predict", "projection", "will be", "next month", "next year")
INJECTION = re.compile(
    r"select\s.+\sfrom\s|drop table|insert into|delete from|ignore (all |any )?(previous|prior|your) "
    r"(instructions|rules)|system prompt|password|connection string|api key|secret"
)
DATA_WORDS = (
    "data",
    "temperature",
    "temp",
    "salinity",
    "salt",
    "pressure",
    "profile",
    "float",
    "argo",
    "ocean",
    "sea",
    "depth",
    "water",
    "warm",
    "cold",
    "observation",
    "measurement",
    "dbar",
    "bay",
    "gulf",
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def _next_month(year: int, month: int) -> datetime:
    return _month_start(year + (month == 12), 1 if month == 12 else month + 1)


def _shift_months(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    day = min(value.day, calendar.monthrange(year, month + 1)[1])
    return value.replace(year=year, month=month + 1, day=day)


def _number(text: str) -> int | None:
    text = text.strip().lower()
    if text.isdigit():
        return int(text)
    return WORD_NUMBERS.get(text)


class _Clarify(Exception):
    def __init__(self, missing: str, question: str) -> None:
        super().__init__(missing)
        self.missing = missing
        self.question = question


class _Unsupported(Exception):
    pass


class RulesPlanner:
    """``offline-rules-v1``. Every method is a pure function of the question and context."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.question = str(context.get("question", ""))
        self.text = " " + re.sub(r"\s+", " ", self.question.lower()).strip() + " "
        reference = context.get("reference_time") or "2025-04-01T00:00:00Z"
        self.now = datetime.fromisoformat(str(reference).replace("Z", "+00:00")).astimezone(UTC)
        self.regions: list[str] = list(context.get("regions") or [])
        self.aliases: dict[str, str] = {}
        for document in context.get("documents") or []:
            metadata = document.get("metadata") or {}
            if document.get("doc_type") == "region_alias" and metadata.get("region"):
                for alias in metadata.get("aliases") or []:
                    self.aliases[str(alias).lower()] = str(metadata["region"])
        self.time_span_days = int(context.get("time_span_days") or 366)

    # ----- intent ------------------------------------------------------------------------------

    def intent(self) -> str | None:
        text = self.text
        if INJECTION.search(text):
            raise _Unsupported(
                "I only answer questions about Argo temperature, salinity and pressure "
                "observations; I do not run SQL or reveal configuration."
            )
        if any(word in text for word in BGC_WORDS):
            raise _Unsupported(
                "Biogeochemical variables (oxygen, chlorophyll, nitrate, pH) are not available "
                "in this version; FloatChat serves temperature, salinity and pressure."
            )
        if any(word in text for word in FORECAST_WORDS):
            raise _Unsupported("Forecasts arrive with Stage 6; I can describe observed data.")
        if any(word in text for word in EXPORT_WORDS):
            raise _Unsupported(
                "Exports and downloads arrive with Stage 5; I can show results in the browser."
            )
        if not any(word in text for word in DATA_WORDS) and not re.search(r"\d{4}", text):
            raise _Unsupported(
                "I answer questions about Argo temperature, salinity and pressure observations."
            )
        return None

    # ----- time -------------------------------------------------------------------------------

    def _month_ref(self, name: str, year: int) -> tuple[datetime, datetime]:
        month = MONTHS[name.lower()]
        return _month_start(year, month), _next_month(year, month)

    def time_range(self) -> tuple[datetime, datetime]:
        text = self.text
        now = self.now
        # ISO day pairs and single ISO days.
        isos = re.findall(r"(\d{4}-\d{2}-\d{2})", text)
        if len(isos) >= 2:
            start = datetime.fromisoformat(isos[0]).replace(tzinfo=UTC)
            end = datetime.fromisoformat(isos[1]).replace(tzinfo=UTC)
            if " to " in text or "between" in text or "from" in text or "-" in text:
                return start, end + timedelta(days=1)
        if len(isos) == 1:
            day = datetime.fromisoformat(isos[0]).replace(tzinfo=UTC)
            if re.search(r"(since|from|after|starting) " + isos[0], text):
                return day, now
            return day, day + timedelta(days=1)
        # Day ranges inside one month: "1-15 March 2025", "March 1-15, 2025", "March 1 to 15 2025".
        m = re.search(
            rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+{MONTH_WORD}\s+(\d{{4}})",
            text,
        )
        if not m:
            m2 = re.search(
                rf"{MONTH_WORD}\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})",
                text,
            )
            if m2:
                name, a, b, year = m2.group(1), m2.group(2), m2.group(3), m2.group(4)
                month = MONTHS[name]
                return (
                    datetime(int(year), month, int(a), tzinfo=UTC),
                    datetime(int(year), month, int(b), tzinfo=UTC) + timedelta(days=1),
                )
        else:
            a, b, name, year = m.group(1), m.group(2), m.group(3), m.group(4)
            month = MONTHS[name]
            return (
                datetime(int(year), month, int(a), tzinfo=UTC),
                datetime(int(year), month, int(b), tzinfo=UTC) + timedelta(days=1),
            )
        m = re.search(
            rf"week (?:starting|beginning|of)\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+{MONTH_WORD}\s+(\d{{4}})",
            text,
        )
        if m:
            start = datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=UTC)
            return start, start + timedelta(days=7)
        # Single days: "15 March 2025", "March 15, 2025".
        m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_WORD}\s+(\d{{4}})", text)
        if m:
            day = datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=UTC)
            return day, day + timedelta(days=1)
        m = re.search(rf"{MONTH_WORD}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", text)
        if m:
            day = datetime(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)), tzinfo=UTC)
            return day, day + timedelta(days=1)
        # Month ranges: "January to March 2025", "between Jan 2025 and Mar 2025", "Jan-Mar 2025".
        m = re.search(
            rf"{MONTH_WORD}(?:\s+(\d{{4}}))?\s*(?:-|–|to|and|through|until)\s*{MONTH_WORD}\s+(\d{{4}})",
            text,
        )
        if m:
            first, year_a, second, year_b = m.group(1), m.group(2), m.group(3), m.group(4)
            start, _ = self._month_ref(first, int(year_a or year_b))
            _, end = self._month_ref(second, int(year_b))
            return start, end
        # Quarters.
        m = re.search(r"(?:q([1-4])|(first|second|third|fourth) quarter(?: of)?)\s+(\d{4})", text)
        if m:
            index = (
                int(m.group(1))
                if m.group(1)
                else ["first", "second", "third", "fourth"].index(m.group(2)) + 1
            )
            year = int(m.group(3))
            return _month_start(year, 3 * index - 2), _next_month(year, 3 * index)
        # "since January 2025" and "from February 2025 (onwards)".
        m = re.search(rf"(since|from|after|starting)\s+{MONTH_WORD}\s+(\d{{4}})", text)
        if m and not re.search(rf"{MONTH_WORD}\s+\d{{4}}\s*(to|and|-|–)", text):
            start, _ = self._month_ref(m.group(2), int(m.group(3)))
            return start, now
        # One month: "January 2025", "2025-01".
        m = re.search(rf"{MONTH_WORD}\s+(\d{{4}})", text)
        if m:
            return self._month_ref(m.group(1), int(m.group(2)))
        m = re.search(r"(\d{4})-(\d{2})(?!-)", text)
        if m:
            return _month_start(int(m.group(1)), int(m.group(2))), _next_month(
                int(m.group(1)), int(m.group(2))
            )
        # Relative phrases against the reference time.
        if re.search(r"last month|previous month|past month", text):
            start = _shift_months(_month_start(now.year, now.month), -1)
            return start, _month_start(now.year, now.month)
        if re.search(r"this month|current month", text):
            return _month_start(now.year, now.month), _next_month(now.year, now.month)
        m = re.search(r"(?:last|past|previous)\s+(\w+)\s+(month|week|day|year)s?", text)
        if m and _number(m.group(1)) is not None:
            count = _number(m.group(1)) or 0
            unit = m.group(2)
            if unit == "month":
                return _shift_months(now, -count), now
            if unit == "week":
                return now - timedelta(days=7 * count), now
            if unit == "day":
                return now - timedelta(days=count), now
            return now.replace(year=now.year - count), now
        if re.search(r"last week|past week", text):
            return now - timedelta(days=7), now
        if re.search(r"yesterday", text):
            return now - timedelta(days=1), now
        if re.search(r"\btoday\b", text):
            return now, now + timedelta(days=1)
        if re.search(r"last year", text):
            return _month_start(now.year - 1, 1), _month_start(now.year, 1)
        if re.search(r"this year|year to date|so far this year", text):
            return _month_start(now.year, 1), now
        m = re.search(
            r"\b((?:19|20)\d{2})\s*(?:and|to|-|–|through|until)\s*((?:19|20)\d{2})\b", text
        )
        if m:
            return _month_start(int(m.group(1)), 1), _month_start(int(m.group(2)) + 1, 1)
        m = re.search(r"\b(?:in|during|for|of)\s+((?:19|20)\d{2})\b", text)
        if m:
            year = int(m.group(1))
            return _month_start(year, 1), _month_start(year + 1, 1)
        raise _Clarify(
            "time_range",
            "Which time period should I use? For example 'January 2025' or '1-15 March 2025'.",
        )

    # ----- geography ----------------------------------------------------------------------------

    def _coordinate(self, text: str) -> tuple[float, float] | None:
        m = re.search(
            r"(-?\d+(?:\.\d+)?)\s*°?\s*([ns])\b[,\s]+(-?\d+(?:\.\d+)?)\s*°?\s*([ew])\b", text
        )
        if m:
            lat = float(m.group(1)) * (-1 if m.group(2) == "s" else 1)
            lon = float(m.group(3)) * (-1 if m.group(4) == "w" else 1)
            return lon, lat
        m = re.search(
            r"(-?\d+(?:\.\d+)?)\s*°?\s*([ew])\b[,\s]+(-?\d+(?:\.\d+)?)\s*°?\s*([ns])\b", text
        )
        if m:
            lon = float(m.group(1)) * (-1 if m.group(2) == "w" else 1)
            lat = float(m.group(3)) * (-1 if m.group(4) == "s" else 1)
            return lon, lat
        m = re.search(
            r"lat(?:itude)?\s*(-?\d+(?:\.\d+)?)\D+lon(?:gitude)?\s*(-?\d+(?:\.\d+)?)", text
        )
        if m:
            return float(m.group(2)), float(m.group(1))
        m = re.search(
            r"lon(?:gitude)?\s*(-?\d+(?:\.\d+)?)\D+lat(?:itude)?\s*(-?\d+(?:\.\d+)?)", text
        )
        if m:
            return float(m.group(1)), float(m.group(2))
        return None

    def _radius(self) -> float | None:
        m = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(km|kilomet)", self.text)
        if m:
            return float(m.group(1))
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:km|kilometers|kilometres)\s+(?:of|from|around)", self.text
        )
        if m:
            return float(m.group(1))
        return None

    def _bbox(self) -> dict[str, Any] | None:
        text = self.text
        m = re.search(
            r"bbox\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
            text,
        )
        if m:
            west, south, east, north = (float(m.group(i)) for i in range(1, 5))
            return {"kind": "bbox", "west": west, "south": south, "east": east, "north": north}
        m = re.search(
            r"\bbox\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
            text,
        )
        if m:
            west, south, east, north = (float(m.group(i)) for i in range(1, 5))
            return {"kind": "bbox", "west": west, "south": south, "east": east, "north": north}
        lon_words = re.search(
            r"longitudes?\s+(-?\d+(?:\.\d+)?)\s*(?:and|to|-|–)\s*(-?\d+(?:\.\d+)?)\b(?!\s*[ew])",
            text,
        )
        lat_words = re.search(
            r"latitudes?\s+(-?\d+(?:\.\d+)?)\s*(?:and|to|-|–)\s*(-?\d+(?:\.\d+)?)\b(?!\s*[ns])",
            text,
        )
        if lon_words and lat_words:
            south, north = sorted((float(lat_words.group(1)), float(lat_words.group(2))))
            return {
                "kind": "bbox",
                "west": float(lon_words.group(1)),
                "south": south,
                "east": float(lon_words.group(2)),
                "north": north,
            }
        lon = re.search(
            r"(-?\d+(?:\.\d+)?)\s*°?\s*([ew])?\s*(?:and|to|-|–)\s*(-?\d+(?:\.\d+)?)\s*°?\s*([ew])\b",
            text,
        )
        lat = re.search(
            r"(-?\d+(?:\.\d+)?)\s*°?\s*([ns])?\s*(?:and|to|-|–)\s*(-?\d+(?:\.\d+)?)\s*°?\s*([ns])\b",
            text,
        )
        if lon and lat:

            def signed(value: str, hemisphere: str | None, negative: str) -> float:
                return float(value) * (-1 if hemisphere == negative else 1)

            west = signed(lon.group(1), lon.group(2) or lon.group(4), "w")
            east = signed(lon.group(3), lon.group(4), "w")
            south = signed(lat.group(1), lat.group(2) or lat.group(4), "s")
            north = signed(lat.group(3), lat.group(4), "s")
            if south > north:
                south, north = north, south
            return {"kind": "bbox", "west": west, "south": south, "east": east, "north": north}
        return None

    def geography(self) -> dict[str, Any]:
        text = self.text
        for alias in sorted(self.aliases, key=len, reverse=True):
            if re.search(r"\b" + re.escape(alias) + r"\b", text):
                return {"kind": "named_region", "value": self.aliases[alias]}
        if "iho" in text and "Indian Ocean (IHO)" in self.regions and "indian ocean" in text:
            return {"kind": "named_region", "value": "Indian Ocean (IHO)"}
        for name in sorted(self.regions, key=len, reverse=True):
            if " " + name.lower() + " " in text or (name.lower() in text and "(" in name):
                return {"kind": "named_region", "value": name}
        box = self._bbox()
        if box is not None:
            return box
        point = self._coordinate(text)
        if point is not None:
            radius = self._radius()
            if radius is None:
                radius = 500.0 if self.is_nearest() else 200.0
            if radius is not None:
                return {
                    "kind": "point_radius",
                    "longitude": point[0],
                    "latitude": point[1],
                    "radius_km": radius,
                }
        raise _Clarify(
            "geography",
            "Which area should I use? A named region (for example the Arabian Sea), a bounding "
            "box, or a point with a radius.",
        )

    # ----- depth, variables, qc ---------------------------------------------------------------

    def depth(self) -> dict[str, float] | None:
        text = self.text
        unit = r"(?:dbar|db|m|metres|meters|decibars?)"
        m = re.search(rf"(\d+(?:\.\d+)?)\s*(?:-|–|to|and)\s*(\d+(?:\.\d+)?)\s*{unit}\b", text)
        if m and (
            "depth" in text
            or "dbar" in text
            or "deep" in text
            or "upper" in text
            or "between" in text
            or "layer" in text
            or " m " in text
        ):
            return {"min": float(m.group(1)), "max": float(m.group(2))}
        m = re.search(rf"(?:upper|top|first|shallowest)\s+(\d+(?:\.\d+)?)\s*{unit}\b", text)
        if m:
            return {"min": 0.0, "max": float(m.group(1))}
        m = re.search(rf"(?:below|deeper than|beneath|under)\s+(\d+(?:\.\d+)?)\s*{unit}\b", text)
        if m:
            return {"min": float(m.group(1)), "max": MAX_DEPTH_DBAR}
        m = re.search(
            rf"(?:above|shallower than|down to|to a depth of)\s+(\d+(?:\.\d+)?)\s*{unit}\b", text
        )
        if m:
            return {"min": 0.0, "max": float(m.group(1))}
        m = re.search(rf"(?:at|around|near)\s+(\d+(?:\.\d+)?)\s*{unit}\b(?:\s+depth)?", text)
        if m:
            centre = float(m.group(1))
            return {"min": max(0.0, centre - 50.0), "max": centre + 50.0}
        if re.search(r"\b(surface|near-surface|sea surface|sst)\b", text):
            return {"min": 0.0, "max": 10.0}
        return None

    def variables(self) -> list[str]:
        text = self.text
        found = []
        if re.search(r"temperature|\btemp\b|warm|cold|hot|cool|heat|thermal|sst", text):
            found.append("temperature")
        if re.search(r"salin|\bsalt|psu|haline|fresh(?:er|est|ness)?\b", text):
            found.append("salinity")
        if re.search(r"\bpressure\b", text):
            found.append("pressure")
        if re.search(r"t-s|t/s|ts diagram|temperature[- ]salinity", text):
            found = ["temperature", "salinity"]
        return found or ["temperature", "salinity"]

    def qc_policy(self, operation: str) -> str:
        text = self.text
        if re.search(r"\braw\b|unfiltered|every (stored )?column|all columns", text):
            return "raw" if operation == "profiles" else "mode_selected"
        if re.search(
            r"regardless of (qc|quality)|ignor(e|ing) (the )?(qc|quality)|qc ignored|any qc|without qc|without quality|as delivered|including (bad|flagged)|flags? beside|with (the )?qc flags?|show(ing)? (the )?(qc )?flags?",
            text,
        ):
            return "mode_selected"
        return "science_ready"

    # ----- operation, presentation ----------------------------------------------------------------

    def is_nearest(self) -> bool:
        return bool(re.search(r"nearest|closest|near(?:by)? float", self.text))

    def operation_and_presentation(
        self, start: datetime, end: datetime, geography: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        text = self.text
        span_days = (end - start).days
        if self.is_nearest():
            point = self._coordinate(text)
            if point is None and geography.get("kind") == "point_radius":
                point = (geography["longitude"], geography["latitude"])
            if point is None:
                raise _Clarify(
                    "geography", "Nearest to which point? Give a latitude and longitude."
                )
            m = re.search(r"(\d+|\w+)\s+(?:nearest|closest)", text)
            if m is None or _number(m.group(1)) is None:
                m = re.search(r"(?:nearest|closest)\s+(\d+|\w+)\s+(?:floats?|profiles?)", text)
            if m is None or _number(m.group(1)) is None:
                m = re.search(
                    r"(\d+|\w+)\s+(?:floats?|profiles?)\s+(?:are|is)?\s*(?:the\s+)?(?:nearest|closest)",
                    text,
                )
            k = _number(m.group(1)) if m else None
            operation: dict[str, Any] = {
                "kind": "nearest",
                "longitude": point[0],
                "latitude": point[1],
                "radius_km": self._radius() or 500.0,
                "k": k or 5,
            }
            presentation: dict[str, Any] = (
                {"kind": "map"}
                if re.search(r"\bmap\b|\bwhere\b|locations?\b|positions?\b", text)
                else {"kind": "table"}
            )
            geography = {
                "kind": "point_radius",
                "longitude": point[0],
                "latitude": point[1],
                "radius_km": operation["radius_km"],
            }
            return operation, presentation, geography
        wants_histogram = bool(re.search(r"histogram|distribution", text))
        wants_ts = bool(re.search(r"t-s|t/s|ts diagram|temperature[- ]salinity diagram", text))
        wants_profile_plot = bool(
            re.search(
                r"profile plot|vertical (?:temperature |salinity )?profiles?|against (depth|pressure)|versus depth|vs\.? depth|with depth",
                text,
            )
        )
        wants_map = bool(re.search(r"\bmap\b|\bwhere\b|locations?\b|positions?\b", text))
        wants_line = bool(
            re.search(
                r"time series|trend|over time|evolution|chart|plot|graph|monthly|daily|per month|per day|each month|each day",
                text,
            )
        )
        wants_scatter = bool(re.search(r"scatter", text))
        aggregate_words = bool(
            re.search(
                r"mean|average|avg|median|minimum|maximum|\bmin\b|\bmax\b|lowest|highest|coldest|warmest|hottest|saltiest|freshest|std|standard deviation|variab|spread|how many|count|number of|statistic|summar",
                text,
            )
        )
        profile_words = bool(
            re.search(
                r"\b(list|show|give|get|find|which|what)\b.*\b(profiles?|floats?)\b|\bprofiles\b.*\b(list|show)\b|^\s*(the\s+)?(\d+\s+)?(newest\s+|latest\s+|raw\s+|unfiltered\s+)?(temperature|salinity|and|\s)*profiles\b|\bprofiles\s+(in|off|near|from|within|of|between|on|during|for)\b",
                text,
            )
        )
        if (
            wants_ts
            or wants_profile_plot
            or (profile_words and not aggregate_words and not wants_histogram and not wants_line)
        ):
            limit = next(
                (
                    _number(found)
                    for found in re.findall(
                        r"(\d+|\w+)\s+(?:newest|latest|most recent|recent|profiles)", text
                    )
                    if _number(found) is not None
                ),
                None,
            )
            if wants_ts or wants_profile_plot:
                limit = limit or 20
            operation = {"kind": "profiles", "limit": limit or 100}
            if wants_ts:
                presentation = {"kind": "ts_diagram"}
            elif wants_profile_plot:
                presentation = {"kind": "profile_plot"}
            elif wants_map:
                presentation = {"kind": "map"}
            else:
                presentation = {"kind": "table"}
            return operation, presentation, geography
        if wants_map and not aggregate_words and not wants_histogram:
            return {"kind": "profiles", "limit": 100}, {"kind": "map"}, geography
        # Aggregate. "profile mean(s)" and "per-profile mean" name the unit, not a metric.
        text = re.sub(r"(per[- ])?profile[- ]means?\b", "profile value", text)
        metrics: list[str] = []
        if re.search(r"mean|average|avg|typical", text):
            metrics.append("mean")
        if re.search(r"how many|count|number of", text):
            metrics.append("count")
        if re.search(r"minimum|\bmin\b|lowest|coldest|freshest|coolest", text):
            metrics.append("min")
        if re.search(r"maximum|\bmax\b|highest|warmest|hottest|saltiest", text):
            metrics.append("max")
        if re.search(r"median", text):
            metrics.append("median")
        if re.search(r"std|standard deviation|variab|spread", text):
            metrics.append("stddev")
        if re.search(r"\brange\b", text) and "time" not in text:
            for metric in ("min", "max"):
                if metric not in metrics:
                    metrics.append(metric)
        if not metrics:
            metrics = ["mean"]
        group_by: list[str] = []
        depth_bin_size: int | None = None
        if re.search(r"per day|daily|each day|by day|day by day", text):
            group_by.append("day")
        elif re.search(
            r"per month|monthly|each month|by month|month by month|month-by-month", text
        ):
            group_by.append("month")
        elif (
            wants_line or re.search(r"trend|over time|evolution|time series", text)
        ) and not wants_histogram:
            group_by.append("day" if span_days <= 31 else "month")
        if re.search(r"per float|each float|by float|float by float", text):
            group_by.append("float")
        if (
            re.search(r"per profile|each profile|by profile|profile by profile", text)
            or wants_histogram
        ):
            if "profile" not in group_by:
                group_by.append("profile")
        m = re.search(
            r"(\d+)\s*(?:dbar|m|metre|meter)\s*(?:depth )?bins?|(\d+)\s*depth bins?", text
        )
        if m or re.search(r"by depth|per depth|depth bin|with depth|versus depth|vs depth", text):
            size = int(m.group(1) or m.group(2)) if m else 50
            size = min((10, 25, 50, 100), key=lambda candidate: abs(candidate - size))
            group_by.append("depth_bin")
            depth_bin_size = size
        if re.search(r"by region|per region|each region|region by region", text):
            group_by.append("region")
        if not ({"month", "day", "profile"} & set(group_by)) and span_days > 31:
            group_by.insert(0, "month")
        unit = (
            "measurement"
            if re.search(
                r"per measurement|each measurement|every measurement|all levels|per level|each level|every level|measurement[- ]level|\bmeasurements\b|\blevels\b|at any level|any level",
                text,
            )
            else "profile"
        )
        operation = {
            "kind": "aggregate",
            "group_by": group_by,
            "metrics": metrics,
            "unit": unit,
        }
        if depth_bin_size is not None:
            operation["depth_bin_size"] = depth_bin_size
        if wants_histogram:
            m = re.search(r"(\d+)\s+bins", text)
            presentation = {"kind": "histogram"}
            if m:
                presentation["bins"] = int(m.group(1))
        elif wants_scatter:
            presentation = {"kind": "scatter"}
        elif wants_line and ({"month", "day"} & set(group_by)):
            presentation = {"kind": "line_chart"}
        else:
            presentation = {"kind": "table"}
        return operation, presentation, geography

    # ----- the answer ------------------------------------------------------------------------------

    def answer(self) -> dict[str, Any]:
        try:
            self.intent()
            start, end = self.time_range()
            if (end - start).days > self.time_span_days:
                raise _Unsupported(
                    f"Requests longer than {self.time_span_days} days run as historical jobs "
                    "(Stage 5); please narrow the period."
                )
            geography = self.geography()
            operation, presentation, geography = self.operation_and_presentation(
                start, end, geography
            )
            variables = self.variables()
            if presentation["kind"] == "ts_diagram":
                variables = ["temperature", "salinity", "pressure"]
            plan: dict[str, Any] = {
                "time_range": {"start": _iso(start), "end": _iso(end)},
                "geography": geography,
                "variables": variables,
                "qc_policy": self.qc_policy(operation["kind"]),
                "operation": operation,
                "presentation": presentation,
            }
            depth = self.depth()
            if depth is not None:
                plan["depth_dbar"] = depth
            return {"kind": "plan", "plan": plan}
        except _Clarify as clarify:
            return {
                "kind": "clarify",
                "clarification": {"missing": [clarify.missing], "question": clarify.question},
            }
        except _Unsupported as unsupported:
            return {"kind": "unsupported", "reason": str(unsupported)}


class OfflineProvider:
    name = "offline"
    model = OFFLINE_MODEL
    embedding_model = OFFLINE_EMBEDDING_MODEL

    def structured(self, request: StructuredRequest) -> StructuredResult:
        if request.purpose == "plan":
            data: Any = RulesPlanner(request.context).answer()
        else:
            data = {"text": str(request.context.get("template", ""))}
        return StructuredResult(data=data, raw_text="", usage=Usage(), model=self.model)

    def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbedResult:
        return EmbedResult(hash_embed_many(texts), Usage(), self.embedding_model)

    def stream_text(self, request: TextRequest) -> TextStream:
        template = str(request.context.get("template", ""))
        words = template.split(" ")
        chunks = (
            (" " if index else "") + " ".join(words[index : index + 6])
            for index in range(0, len(words), 6)
        )
        return TextStream(chunks, self.model)
