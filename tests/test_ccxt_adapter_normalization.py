"""Phase 8 CCXT adapter tests — untrusted raw; P1 is the validation authority.

Offline: the pure converter is tested directly, and the network path is exercised
against a FAKE in-memory ``ccxt`` module (no real dependency, no network). Proves
public/keyless construction and that invalid exchange data is never turned into a
valid-empty success.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from app.exceptions import AdapterError, UnsupportedMarketError
from app.market_data.ccxt_adapter import CcxtMarketDataAdapter, raw_candles_from_ohlcv
from app.market_data.models import Symbol, Timeframe
from app.market_data.validation import IssueCode, validate_candles

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# --- pure converter -------------------------------------------------------
def test_converter_string_and_numeric_fields() -> None:
    rows = [
        [_ms(BASE), 100.5, 101, 99, 100.2, 5.0],  # numeric (float/int)
        [str(_ms(BASE + timedelta(hours=1))), "100.2", "102", "99", "101", "6"],  # strings
    ]
    out = raw_candles_from_ohlcv(rows, source="binance", symbol="BTC/USDT", timeframe="1h")
    assert len(out) == 2
    assert out[0].open_time == BASE
    assert out[0].open == "100.5" and out[0].high == "101"  # float→str, int→str
    assert out[1].open == "100.2"  # str passthrough
    assert out[1].open_time == BASE + timedelta(hours=1)


def test_converter_malformed_shape_raises() -> None:
    with pytest.raises(AdapterError):
        raw_candles_from_ohlcv([[1, 2, 3]], source="x", symbol="BTC/USDT", timeframe="1h")
    with pytest.raises(AdapterError):
        raw_candles_from_ohlcv({"not": "a list"}, source="x", symbol="BTC/USDT", timeframe="1h")


def test_converter_bad_timestamp_is_passed_through_not_valid_empty() -> None:
    # A non-numeric timestamp becomes None → P1 flags it (never silently dropped).
    rows = [["not-a-ts", 1, 1, 1, 1, 1]]
    out = raw_candles_from_ohlcv(rows, source="x", symbol="BTC/USDT", timeframe="1h")
    assert len(out) == 1 and out[0].open_time is None


def test_p1_remains_validation_authority_for_dupes_future_incomplete() -> None:
    now = BASE + timedelta(hours=3)  # candles 0,1,2 closed; candle at hour 3 is current
    rows = [
        [_ms(BASE), 100, 101, 99, 100, 5],
        [_ms(BASE), 100, 101, 99, 100, 5],  # DUPLICATE open_time
        [_ms(BASE + timedelta(hours=3)), 100, 101, 99, 100, 5],  # incomplete/current
        [_ms(BASE + timedelta(hours=48)), 100, 101, 99, 100, 5],  # FUTURE
    ]
    raw = raw_candles_from_ohlcv(rows, source="binance", symbol="BTC/USDT", timeframe="1h")
    _candles, result = validate_candles(
        raw, symbol=Symbol.parse("BTC/USDT"), timeframe=Timeframe.H1, now=now
    )
    codes = {i.code for i in result.issues}
    assert IssueCode.DUPLICATE in codes
    assert IssueCode.FUTURE_TIMESTAMP in codes
    assert result.quality.incomplete_count >= 1  # the current candle
    assert not result.usable  # invalid series is NOT a valid-empty success


# --- network path against a FAKE ccxt (keyless + error mapping) -----------
class _FakeExchange:
    captured_config: dict | None = None

    def __init__(self, config: dict) -> None:
        type(self).captured_config = dict(config)

    def fetch_ohlcv(self, symbol, timeframe, since, limit):  # noqa: ANN001
        return [[_ms(BASE), 100, 101, 99, 100, 5]]

    def milliseconds(self) -> int:
        return _ms(BASE)


class _RaisingExchange(_FakeExchange):
    def fetch_ohlcv(self, symbol, timeframe, since, limit):  # noqa: ANN001
        raise RuntimeError("429 rate limit exceeded")


def _install_fake_ccxt(monkeypatch, exchange_cls) -> None:
    fake = types.ModuleType("ccxt")
    fake.binance = exchange_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ccxt", fake)


def test_ccxt_adapter_is_public_keyless(monkeypatch) -> None:
    _FakeExchange.captured_config = None
    _install_fake_ccxt(monkeypatch, _FakeExchange)
    adapter = CcxtMarketDataAdapter(exchange_id="binance")
    out = adapter.fetch_ohlcv(Symbol.parse("BTC/USDT"), Timeframe.H1)
    assert len(out) == 1
    cfg = _FakeExchange.captured_config
    assert cfg is not None
    # NO trading credentials are ever passed to the exchange client.
    assert "apiKey" not in cfg and "secret" not in cfg and "password" not in cfg


def test_ccxt_adapter_maps_errors_to_adaptererror(monkeypatch) -> None:
    _install_fake_ccxt(monkeypatch, _RaisingExchange)
    adapter = CcxtMarketDataAdapter(exchange_id="binance")
    with pytest.raises(AdapterError):
        adapter.fetch_ohlcv(Symbol.parse("BTC/USDT"), Timeframe.H1)


def test_ccxt_adapter_unknown_exchange_raises(monkeypatch) -> None:
    _install_fake_ccxt(monkeypatch, _FakeExchange)
    adapter = CcxtMarketDataAdapter(exchange_id="does_not_exist")
    with pytest.raises(UnsupportedMarketError):
        adapter.fetch_ohlcv(Symbol.parse("BTC/USDT"), Timeframe.H1)


def test_ccxt_adapter_requires_exchange_id() -> None:
    with pytest.raises(ValueError):
        CcxtMarketDataAdapter(exchange_id="")
