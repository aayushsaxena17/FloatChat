"""Test-only barriers around real production procedures, in a disposable DB.

Never imported by production entrypoints. Barriers do not replace work, change
scientific decisions, shorten deadlines or grant scientific DML privileges.

The probe starts the real queue workers through `main` below. The acquire process runs its
threads in one interpreter, so patching Repository here covers them. Process-pool children
are fresh spawned interpreters: the pool starts them with `run_ticket` below, which is
importable from this module, so they apply the same patches when they import it.
"""

import os
import sys

from floatchat_core.ingestion.repository import Repository
from floatchat_workers import cli, process


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

original_run_ticket = process.run_ticket


def run_ticket(run, chunk, identifier):
    """Pool child entrypoint; importing this module in the child installed the barriers."""
    original_run_ticket(run, chunk, identifier)


process.run_ticket = run_ticket


def main(arguments):
    """The production CLI with barriers: acquire --slots N, process --workers M, supervise."""
    return cli.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
