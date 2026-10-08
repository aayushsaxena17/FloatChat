"""Deterministic synthetic derivatives; never attributed as live Argovis captures."""

import copy
import json
import socket
from pathlib import Path

import pytest
from floatchat_core.ingestion.numeric import decode_json

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "tests/fixtures/argovis/examples"


@pytest.fixture(autouse=True)
def deny_upstream(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Stage 1 tests deny all Python socket connections")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture
def wire():
    # Synthetic identity/time/location/data join from unrelated published outputs.
    # The join is deliberately not represented as a recorded HTTP response.
    document = json.loads((EXAMPLES / "published_inventory_profile.json").read_text())[0]
    arrays = json.loads((EXAMPLES / "published_temperature_pressure_arrays.json").read_text())
    document["timestamp"] = "2025-01-15T00:00:00Z"
    document["geolocation"]["coordinates"] = [70, 10]
    document["data_info"] = json.loads((EXAMPLES / "published_data_info.json").read_text())
    document["data"] = [x[:3] for x in arrays]
    return copy.deepcopy(document)


@pytest.fixture
def linked_metadata():
    return {d["_id"]: d for d in decode_json((EXAMPLES / "published_metadata.json").read_bytes())}
