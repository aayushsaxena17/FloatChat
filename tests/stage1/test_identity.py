import json
import uuid
from dataclasses import replace

import pytest
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.identity import StoredIdentity, resolve_identity
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json


def profile(wire, metadata):
    return map_profile(decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget())


def test_I03_stable_alias_no_extra_science(wire, linked_metadata):
    candidate = profile(wire, linked_metadata)
    row = StoredIdentity(
        uuid.uuid4(),
        candidate.platform,
        None,
        candidate.cycle,
        candidate.direction,
        candidate.natural_key,
    )
    decision = resolve_identity(candidate, (row,))
    assert decision.stored_id == row.id and decision.action == "attach_stable_alias"
    assert resolve_identity(replace(candidate, source_profile_id=None), (row,)).stored_id == row.id


def test_I03_id_and_key_resolve_different_rows(wire, linked_metadata):
    candidate = profile(wire, linked_metadata)
    keyed = StoredIdentity(
        uuid.uuid4(),
        candidate.platform,
        None,
        candidate.cycle,
        candidate.direction,
        candidate.natural_key,
    )
    identified = replace(
        keyed, id=uuid.uuid4(), source_profile_id=candidate.source_profile_id, natural_key=None
    )
    with pytest.raises(Rejection, match="identity_conflict"):
        resolve_identity(candidate, (keyed, identified))
    with pytest.raises(Rejection, match="identity_conflict"):
        resolve_identity(candidate, (replace(keyed, source_profile_id="different-stable-id"),))


def test_I04_same_stable_id_direction_conflict(wire, linked_metadata):
    candidate = profile(wire, linked_metadata)
    row = StoredIdentity(
        uuid.uuid4(), candidate.platform, candidate.source_profile_id, candidate.cycle, "D", None
    )
    with pytest.raises(Rejection, match="identity_conflict"):
        resolve_identity(candidate, (row,))


def test_R08_stable_time_correction_vs_fallback_correction(wire, linked_metadata):
    candidate = profile(wire, linked_metadata)
    row = StoredIdentity(
        uuid.uuid4(),
        candidate.platform,
        candidate.source_profile_id,
        candidate.cycle,
        candidate.direction,
        candidate.natural_key,
    )
    moved = replace(candidate, observed_at="2025-02-15T00:00:00.000000+00:00")
    assert resolve_identity(moved, (row,)).stored_id == row.id
    with pytest.raises(Rejection, match="fallback_observation_time_correction"):
        resolve_identity(
            replace(moved, source_profile_id=None), (replace(row, source_profile_id=None),)
        )
