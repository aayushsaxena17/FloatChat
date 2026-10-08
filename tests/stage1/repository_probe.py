"""Restricted-role repository proof in a network-isolated disposable database."""

import os
import uuid

from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import Interval, Tile, timestamp
from floatchat_core.ingestion.repository import Authority, Repository

RUN = uuid.UUID("00000000-0000-4000-8000-000000000001")
CHUNK = uuid.UUID("00000000-0000-4000-8000-000000000002")
ENV = uuid.UUID("00000000-0000-4000-8000-000000000003")
INTENT = uuid.UUID("00000000-0000-4000-8000-000000000008")


def main():
    repository = Repository(os.environ["INGESTION_DATABASE_URL"])
    try:
        repository.connection.execute("SET ROLE floatchat_ingestor")
        rows = repository.stored()
        assert len(rows) == 1 and len(rows[0].profile.levels) == 3
        assert rows[0].profile.content_hash == os.environ["EXPECTED_SCIENTIFIC_HASH"]
        interval = Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-01-07T00:00:00Z"))
        result = repository.catalogue_snapshot(ENV, interval, tiles=(Tile(70, 10),))
        assert len(result.records) == 1 and not result.gaps
        assert not result.empty_evidence and not result.source_absence_evidence
        # stage1-v4: the record is the chunk's part and the manifest travels with the snapshot.
        (record,) = result.records
        assert record.kind == "part" and record.part_ordinal == 1
        (manifest,) = result.manifests.values()
        assert [item["hash"] for item in manifest] == [rows[0].profile.content_hash]
        assert repository.science_hashes([rows[0].identity.id])[
            rows[0].identity.id
        ].content_hash == (rows[0].profile.content_hash)
        found = repository.identities_batch([rows[0].profile])[rows[0].profile.identity]
        assert [identity.id for identity in found] == [rows[0].identity.id]
        assert repository.audit_levels(CHUNK, 5) == {"profiles": 1, "levels": 3}
        # Already complete is recognized before expired/stale caller authority or
        # empty proposed generation arguments; nothing new is merged.
        repository.commit(Authority(RUN, CHUNK, 1, 1), INTENT, [], [])
        try:
            repository.connection.execute("DELETE FROM app.argo_profile")
        except Exception:
            pass
        else:
            raise AssertionError("Ingestor acquired unrestricted scientific deletes")
        try:
            repository.stage_candidates(Authority(RUN, CHUNK, 1, 1), ())
        except Rejection as error:
            assert (
                error.category == "invalid_state_transition"
                or error.category == "publication_fenced"
            )
        else:
            raise AssertionError("Terminal publication accepted staging mutation")
        print("offline-restricted-repository-verified")
    finally:
        repository.close()


if __name__ == "__main__":
    main()
