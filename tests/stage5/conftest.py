"""Stage 5 tests deny network sockets; the store, catalogue, ingestion and exporter are doubles."""

import socket

import pytest


@pytest.fixture(autouse=True)
def deny_sockets(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Stage 5 tests deny all Python socket connections")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
