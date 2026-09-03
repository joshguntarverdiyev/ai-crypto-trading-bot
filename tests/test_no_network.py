"""The offline guarantee: the network-blocking fixture is active."""

from __future__ import annotations

import socket

import pytest


def test_network_is_blocked() -> None:
    with pytest.raises(RuntimeError):
        socket.create_connection(("example.com", 80), timeout=1)


def test_dns_is_blocked() -> None:
    with pytest.raises(RuntimeError):
        socket.getaddrinfo("example.com", 80)
