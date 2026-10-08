"""Test-only barriers around real production procedures, in a disposable DB.

Never imported by production entrypoints. Barriers do not replace work, change
scientific decisions, shorten deadlines or grant scientific DML privileges.
"""

import os

from floatchat_core.ingestion.repository import Repository
from floatchat_workers.app import app

app.conf.broker_transport_options = {"visibility_timeout": 10}


def barrier(repository, authority, phase):
    row = repository.connection.execute(
        "SELECT lock_key FROM public.test_fault WHERE chunk_id=%s AND phase=%s AND armed",
        (authority.chunk, phase),
    ).fetchone()
    if row is None:
        return
    repository.connection.execute(
        "INSERT INTO public.test_signal VALUES(%s,%s,%s,pg_backend_pid(),clock_timestamp())",
        (authority.chunk, phase, os.getpid()),
    )
    repository.connection.execute("SELECT pg_advisory_lock(%s)", (row["lock_key"],))
    repository.connection.execute("SELECT pg_advisory_unlock(%s)", (row["lock_key"],))


original_reserve = Repository.recorded_reserve
original_transition = Repository.transition
original_commit = Repository.commit


def recorded_reserve(self, authority, *args, **kwargs):
    result = original_reserve(self, authority, *args, **kwargs)
    barrier(self, authority, "fetching")
    return result


def transition(self, authority, state, *args, **kwargs):
    result = original_transition(self, authority, state, *args, **kwargs)
    if state != "fetching":
        barrier(self, authority, state)
    return result


def commit(self, authority, *args, **kwargs):
    barrier(self, authority, "before_commit")
    result = original_commit(self, authority, *args, **kwargs)
    barrier(self, authority, "after_commit")
    return result


Repository.recorded_reserve = recorded_reserve
Repository.transition = transition
Repository.commit = commit
