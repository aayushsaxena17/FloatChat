"""Stage 1 chunk execution; science becomes visible only in commit_publication."""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .argovis import VARIABLES, bounded_text, integer, map_profile, request_parameters
from .json_stream import documents
from .numeric import Rejection, scientific_number
from .objects import ObjectStore, publish_verified
from .parquet import PublicationSnapshotVerifier, write_snapshot
from .planning import Interval, PlannedChunk, RunPolicy, Tile, in_region, month_start, timestamp
from .repository import Authority, Repository
from .revisions import compare
from .source import Source
from .spool import ProfileSpool, revision_json
from .states import TERMINAL

# OpenAPI 2.36.2 warnings with a defined S1-SOURCE-2 outcome (ADR-0040, ADR-0046).
TOLERATED_WARNINGS = frozenset({"degenerate_levels", "missing_basin"})

SPLITTABLE = frozenset(
    {
        "compressed_size_limit",
        "decompressed_size_limit",
        "profile_count_limit",
        "chunk_scientific_resource_limit",
    }
)
FAILURES = frozenset(
    {
        "landing_unavailable",
        "fixture_selection_unavailable",
        "replay_selection_unavailable",
        "http_retry_exhausted",
        "upstream_transport_failure",
        "http_retry_deadline",
        "io_deadline",
        "object_missing",
        "object_write_failure",
        "object_read_failure",
        "database_failure",
        "database_deadline",
        "snapshot_deadline",
        "object_deadline",
        "live_ingestion_disabled",
        "publication_budget_exhausted",
        "private_spool_size_limit",
    }
)


class Processor:
    def __init__(
        self,
        repository: Repository,
        budget_repository: Repository,
        store: ObjectStore,
        source: Source,
        authority: Authority,
        private: Path,
        *,
        deadline: float,
    ) -> None:
        self.repository, self.budget_repository, self.store, self.source = (
            repository,
            budget_repository,
            store,
            source,
        )
        self.authority, self.private, self.deadline = authority, private, deadline
        self.last_pulse = 0.0
        self.outcomes: list[dict[str, Any]] = []
        self.raw_ids: dict[str, str] = {}
        self.raw_statuses: dict[str, int] = {}
        self.observed_profiles = self.known_levels = self.unknown_level_profiles = (
            self.canonical_input
        ) = 0
        self.meta: dict[str, Path] = {}
        self.raw_paths: dict[str, Path] = {}
        self.inventory_verified = False
        row = repository.chunk(authority.chunk)
        self.plan = PlannedChunk(
            Interval(row["requested_start"], row["requested_end"]), Tile(**row["tile"])
        )
        run = repository.run(authority.run)
        self.policy = RunPolicy(
            run["run_reference_time_utc"], run["mode"], str(run["environment_id"])
        )
        self.environment = run["environment_id"]

    def pulse(self) -> None:
        now = time.monotonic()
        if now >= self.deadline:
            raise Rejection("work_deadline")
        if now - self.last_pulse >= 60:
            self.budget_repository.heartbeat(self.authority)
            self.last_pulse = now

    def landing(self, path: str, parameters: dict[str, str], role: str) -> Path:
        self.pulse()
        result = self.source.obtain(path, parameters, role)
        file = self.private / (uuid.uuid4().hex + ".json")
        with file.open("xb") as output:
            file.chmod(0o600)
            output.write(result.payload)
        self.raw_ids[role] = str(result.manifest["id"])
        self.raw_statuses[role] = int(result.manifest.get("http_status", 200))
        return file

    def metadata(self, document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        pointers = document.get("metadata")
        if not isinstance(pointers, list) or not 1 <= len(pointers) <= 4:
            raise Rejection("invalid_metadata_pointer")
        result = {}
        for pointer in pointers:
            pointer = bounded_text(pointer, 512, "invalid_metadata_pointer")
            if pointer not in self.meta:
                self.meta[pointer] = self.landing("/argo/meta", {"id": pointer}, "metadata")
            rows = list(documents(self.meta[pointer].read_bytes(), max_documents=1))
            if len(rows) != 1 or rows[0].get("_id") != pointer:
                raise Rejection("unresolved_metadata")
            result[pointer] = rows[0]
        return result

    def inventory(self, path: Path) -> frozenset[str]:
        identities = set()
        for doc in documents(path.read_bytes()):
            self.pulse()
            observed = timestamp(doc.get("timestamp", ""))
            point = doc.get("geolocation", {})
            if not isinstance(point, dict) or point.get("type") != "Point":
                raise Rejection("invalid_coordinates")
            coordinates = point.get("coordinates", [])
            if not isinstance(coordinates, list) or len(coordinates) != 2:
                raise Rejection("invalid_coordinates")
            lon, lat = (scientific_number(value, coordinate=True) for value in coordinates)
            if not self.plan.interval.contains(observed) or not in_region(
                Decimal(lon.exact or "NaN"), Decimal(lat.exact or "NaN")
            ):
                continue
            identifier = doc.get("_id")
            if identifier is not None:
                key = "id:" + bounded_text(identifier, 512, "invalid_profile_id")
            else:
                platforms = {
                    bounded_text(meta.get("platform"), 32, "missing_platform")
                    for meta in self.metadata(doc).values()
                }
                direction = doc.get("profile_direction")
                if len(platforms) != 1 or direction not in ("A", "D"):
                    raise Rejection("incomplete_fallback_identity")
                key = "natural:" + json.dumps(
                    (
                        platforms.pop(),
                        integer(doc.get("cycle_number"), "invalid_cycle"),
                        direction,
                        observed.isoformat(timespec="microseconds"),
                        "single",
                    ),
                    separators=(",", ":"),
                )
            identities.add(key)
        return frozenset(identities)

    def accounting(self) -> None:
        self.repository.outcomes(self.authority, self.outcomes)
        self.repository.accounting(
            self.authority,
            {
                "observed_profile_occurrences": self.observed_profiles,
                "known_source_levels": self.known_levels,
                "unknown_level_profiles": self.unknown_level_profiles,
                "canonical_input_bytes": self.canonical_input,
                "inventory_verified": self.inventory_verified,
                "raw_roles": self.raw_ids,
            },
        )

    def inventory_accounting(self) -> None:
        self.outcomes = []
        self.observed_profiles = self.known_levels = self.unknown_level_profiles = 0
        for index, doc in enumerate(documents(self.raw_paths["profile"].read_bytes())):
            self.pulse()
            self.observed_profiles += 1
            arrays = doc.get("data")
            lengths = (
                {len(array) for array in arrays if isinstance(array, list)}
                if isinstance(arrays, list)
                else set()
            )
            count = (
                next(iter(lengths))
                if isinstance(arrays, list)
                and arrays
                and len(lengths) == 1
                and all(isinstance(a, list) for a in arrays)
                else None
            )
            if count is None:
                self.unknown_level_profiles += 1
            else:
                self.known_levels += count
            outcome: dict[str, Any] = {
                "index": index,
                "identity": None,
                "outcome": "blocked_uncommitted",
                "levels": count,
                "unknown_levels_reason": "invalid_source_arrays" if count is None else None,
                "hash": None,
                "evidence": {},
            }
            self.outcomes.append(outcome)

    def map(self, spool: ProfileSpool) -> None:
        for index, doc in enumerate(documents(self.raw_paths["profile"].read_bytes())):
            self.pulse()
            outcome = self.outcomes[index]
            outcome["outcome"] = "structurally_quarantined"
            # S1-SOURCE-2 (ADR-0040/0046): degenerate_levels excludes the whole profile;
            # missing_basin is an informational label (valid position, land-adjacent
            # basin lookup) and publishes normally. The rest of the schema must still
            # validate; missing_location/missing_timestamp, any other or repeated
            # warning, missing identity or drift keep the strict whole-chunk quarantine.
            warnings = doc.get("data_warning", [])
            source_loss = informational = False
            if (
                isinstance(warnings, list)
                and warnings
                and len(set(warnings)) == len(warnings)
                and set(warnings) <= TOLERATED_WARNINGS
            ):
                if not doc.get("_id"):
                    raise Rejection("upstream_data_warning")
                source_loss = "degenerate_levels" in warnings
                informational = "missing_basin" in warnings
                doc = {**doc, "data_warning": []}
            with self.budget_repository.canonical_budget(self.authority) as budget:
                value = map_profile(doc, self.metadata(doc), budget)
            self.canonical_input += len(value.canonical_bytes)
            if self.canonical_input > 256 * 1024**2 or self.known_levels > 2_000_000:
                raise Rejection("chunk_scientific_resource_limit")
            outcome.update(
                identity=value.identity,
                hash=value.content_hash,
                levels=len(value.levels),
                unknown_levels_reason=None,
                evidence={"incoming_revision": json.loads(revision_json(value.revision))},
            )
            observed = timestamp(value.observed_at)
            lon, lat = (
                Decimal(value.longitude.exact or "NaN"),
                Decimal(value.latitude.exact or "NaN"),
            )
            normal_outside = not self.policy.eligible.contains(observed) or not in_region(lon, lat)
            if (
                normal_outside
                and self.policy.mode == "normal"
                and value.source_profile_id is not None
            ):
                for identity in self.repository.identities(value):
                    if identity.source_profile_id == value.source_profile_id:
                        with self.budget_repository.canonical_budget(self.authority) as budget:
                            previous = self.repository.load_science(identity.id, budget)
                        if compare(
                            value.content_hash,
                            value.revision,
                            previous.content_hash,
                            previous.revision,
                        ) in ("newer", "revision_conflict"):
                            raise Rejection("correction_requires_lifecycle_review")
            names = doc["data_info"][0]
            has_core = any(
                name in VARIABLES or any(name.startswith(variable + "_") for variable in VARIABLES)
                for name in names
            )
            if not has_core:
                outcome["outcome"] = "outside_core"
            elif not self.plan.interval.contains(observed):
                outcome["outcome"] = "outside_time"
            elif not in_region(lon, lat):
                outcome["outcome"] = "outside_region"
            elif not self.plan.tile.owns(lon, lat):
                outcome["outcome"] = "overlap_duplicate"
            elif source_loss:
                # Never published: returned levels are recorded, lost inputs unknown.
                outcome["outcome"] = "excluded_source_loss"
                outcome["evidence"] = {
                    **outcome["evidence"],
                    "policy": "S1-SOURCE-2",
                    "warning": "degenerate_levels",
                    "source_warnings": sorted(warnings),
                    "source_profile_id": value.source_profile_id,
                    "raw_profile_landing": self.raw_ids["profile"],
                    "selection": request_parameters(self.plan, inventory=False),
                    "returned_levels": len(value.levels),
                    "lost_levels": "unknown",
                }
            else:
                outcome["outcome"] = "blocked_uncommitted"
                if informational:
                    # The warning itself stays in the immutable raw landing.
                    outcome["evidence"] = {
                        **outcome["evidence"],
                        "source_warnings": ["missing_basin"],
                    }
                spool.add(value, uuid.UUID(self.raw_ids["profile"]), index)

    def execute(self) -> str:
        row = self.repository.chunk(self.authority.chunk)
        if row["state"] in TERMINAL:
            return str(row["state"])
        try:
            self.pulse()
            if row["state"] == "planned":
                self.repository.transition(self.authority, "fetching", "worker_started")
            for selection_attempt in range(4):
                for role in ("inventory_before", "profile", "inventory_after"):
                    self.raw_paths[role] = self.landing(
                        "/argo", request_parameters(self.plan, inventory=role != "profile"), role
                    )
                self.inventory_accounting()
                before = self.inventory(self.raw_paths["inventory_before"])
                current = self.inventory(self.raw_paths["profile"])
                after = self.inventory(self.raw_paths["inventory_after"])
                # S1-SOURCE-2: an empty-delivery 404 counts only as a coherent triple;
                # a mixed 200/404 selection is retried like a changing inventory.
                coherent = len({self.raw_statuses[r] for r in self.raw_paths}) == 1
                if before == current == after and coherent:
                    break
                self.accounting()
                if selection_attempt == 3:
                    raise Rejection("incomplete_inventory")
                self.source.restart_selection()
                self.meta.clear()
                self.raw_paths.clear()
                self.raw_statuses.clear()
            self.inventory_verified = True
            # Resolve every profile's metadata before declaring the landing complete.
            for document in documents(self.raw_paths["profile"].read_bytes()):
                self.metadata(document)
            phase = self.repository.chunk(self.authority.chunk)["state"]
            if phase == "fetching":
                self.repository.transition(self.authority, "landed", "complete_verified_landing")
                phase = "landed"
            if phase == "landed":
                self.repository.transition(self.authority, "validating", "mapping_started")
            return self.publish()
        except Rejection as error:
            if error.category in ("publication_fenced", "run_fenced", "work_deadline"):
                raise
            self.accounting()
            if error.category in SPLITTABLE:
                try:
                    self.repository.split(self.authority)
                    return "split_replaced"
                except Rejection:
                    self.repository.transition(self.authority, "failed", "minimum_chunk_exceeded")
                    return "failed"
            state = "failed" if error.category in FAILURES else "quarantined"
            self.repository.transition(
                self.authority,
                state,
                error.category,
                {
                    **(
                        {"resource_limit": error.resource_evidence}
                        if error.resource_evidence
                        else {}
                    ),
                    "conflicts": [
                        outcome["evidence"]
                        for outcome in self.outcomes
                        if outcome["outcome"] == "revision_conflict"
                    ],
                },
            )
            return state

    def publish(self) -> str:
        # Rebuilds/recovery use the same raw landing, original T and persisted budgets.
        for attempt in range(4):
            self.inventory_accounting()
            self.canonical_input = 0
            with ProfileSpool(
                self.private / (uuid.uuid4().hex + ".sqlite"),
                budget_factory=lambda: self.budget_repository.canonical_budget(self.authority),
            ) as spool:
                self.map(spool)

                def old(identifier: uuid.UUID) -> Any:
                    with self.budget_repository.canonical_budget(self.authority) as budget:
                        return self.repository.load_science(identifier, budget)

                try:
                    spool.prepare(
                        lambda p: (), identity_lookup=self.repository.identities, load_science=old
                    )
                except Rejection:
                    for index, key, result, levels in spool.outcomes:
                        self.outcomes[index].update(identity=key, outcome=result, levels=levels)
                    for index, evidence in spool.conflicts:
                        self.outcomes[index].update(outcome="revision_conflict", evidence=evidence)
                    raise
                for index, key, outcome, levels in spool.outcomes:
                    self.outcomes[index].update(identity=key, outcome=outcome, levels=levels)
                self.accounting()
                self.pulse()
                self.repository.transition(self.authority, "publishing", "validated_candidate")
                owner = Tile(
                    20 + (self.plan.tile.west - 20) // 10 * 10,
                    -60 + (self.plan.tile.south + 60) // 10 * 10,
                )
                own = self.repository.ensure_slot(
                    self.authority, month_start(self.plan.interval.start), owner
                )
                for slot in spool.changed_slots:
                    pieces = slot.split("/")
                    west, south = (int(x) for x in pieces[3].split(":"))
                    self.repository.ensure_slot(
                        self.authority, timestamp(pieces[2] + "-01T00:00:00Z"), Tile(west, south)
                    )
                with self.repository.retained_snapshot(
                    self.authority, tuple(sorted(spool.changed_slots)), self.budget_repository
                ) as (bases, rows):
                    spool.retain(rows)
                intent = uuid.uuid4()
                generations = []
                keys = []
                publications = []
                for slot in sorted(spool.changed_slots):
                    membership = spool.membership(slot)
                    generation = {
                        "id": str(uuid.uuid4()),
                        "logical_key": slot,
                        "base_version": bases[slot],
                        "membership_manifest": membership,
                    }
                    if membership:
                        file = self.private / (uuid.uuid4().hex + ".parquet")
                        verified = write_snapshot(
                            file,
                            spool.profiles(slot),
                            deadline=self.deadline,
                            budget_factory=lambda: self.budget_repository.canonical_budget(
                                self.authority
                            ),
                        )
                        digest = hashlib.sha256(file.read_bytes()).hexdigest()
                        final = f"normalised/sha256/{digest}.parquet"
                        temporary = f"tmp/{intent.hex}/{uuid.uuid4().hex}"
                        keys.extend([final, temporary])
                        generation.update(
                            object_key=final,
                            sha256=digest,
                            bytes=file.stat().st_size,
                            row_count=verified["rows"],
                            profile_count=verified["profiles"],
                            schema_sha256=verified["schema_sha256"],
                            verification_evidence=verified,
                            verified_at=datetime.now(UTC).isoformat(),
                        )
                        publications.append(
                            (
                                file,
                                temporary,
                                PublicationSnapshotVerifier(
                                    digest,
                                    file.stat().st_size,
                                    verified,
                                    deadline=self.deadline,
                                    budget_factory=lambda: self.budget_repository.canonical_budget(
                                        self.authority
                                    ),
                                ),
                            )
                        )
                    generations.append(generation)
                self.repository.prepare_intent(self.authority, intent, keys, bases, {})
                for file, temporary, verify_publication in publications:
                    publish_verified(
                        self.store,
                        file.read_bytes(),
                        intent,
                        verify_publication,
                        deadline=self.deadline,
                        temporary_key=temporary,
                    )
                receipts = self.receipts(spool, own)
                staged = self.private / (uuid.uuid4().hex + ".ndjson")
                spool.write_candidates(staged)
                self.repository.stage_file(self.authority, staged)
                self.pulse()
                try:
                    self.repository.commit(self.authority, intent, generations, receipts)
                    return "complete"
                except Rejection as error:
                    if error.category != "publication_base_changed" or attempt == 3:
                        raise
        raise Rejection("publication_budget_exhausted")

    def receipts(self, spool: ProfileSpool, own: str) -> list[dict[str, Any]]:
        result = []
        for slot in sorted(spool.changed_slots | {own}):
            if slot in spool.changed_slots:
                full = spool.membership(slot)
                selected = sum(
                    1
                    for _, p in spool.profiles(slot)
                    if self.plan.interval.contains(timestamp(p.observed_at))
                    and self.plan.tile.owns(
                        Decimal(p.longitude.exact or "NaN"), Decimal(p.latitude.exact or "NaN")
                    )
                )
            else:
                full, selected = self.repository.slot_members(self.authority, slot, self.plan)
            fetch = (
                "profiles_returned"
                if self.observed_profiles
                else "source_absence_over_retained"
                if selected
                else "verified_empty_fetch"
            )
            stored = (
                "empty_stored_domain"
                if slot in spool.changed_slots and not full
                else "active_generation"
                if selected
                else "empty_stored_selection"
            )
            result.append(
                {
                    "id": str(uuid.uuid4()),
                    "logical_key": slot,
                    "fetch_disposition": fetch,
                    "stored_disposition": stored,
                    "evidence": {
                        "raw_roles": self.raw_ids,
                        "full_membership": full,
                        "selected_profiles": selected,
                        "run_reference_time_utc": self.policy.reference.isoformat(),
                    },
                }
            )
        return result
