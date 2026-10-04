from floatchat_workers.app import smoke


def test_smoke_result() -> None:
    assert smoke("stage0") == "ok:stage0"
