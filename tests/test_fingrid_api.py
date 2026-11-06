"""Unit tests for fingrid_api.py.

The real API is never called: requests.get is replaced with a fake that
returns pages we control, so the tests are fast and need no API key.
"""
import pandas as pd
import pytest

import fingrid_api


def make_rows(n, start="2026-10-06T00:00:00Z"):
    """n consecutive 3-minute readings, in the API's JSON format."""
    t0 = pd.Timestamp(start)
    return [
        {
            "datasetId": 192,
            "startTime": (t0 + pd.Timedelta(minutes=3 * i)).isoformat(),
            "endTime": (t0 + pd.Timedelta(minutes=3 * (i + 1))).isoformat(),
            "value": 1000.0 + i,
        }
        for i in range(n)
    ]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fake_api(monkeypatch, rows, reported_total):
    """Serve `rows` page by page, always reporting `reported_total` as the total."""
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(params["page"])
        size = params["pageSize"]
        first = (params["page"] - 1) * size
        return FakeResponse({
            "data": rows[first:first + size],
            "pagination": {"total": reported_total},
        })

    monkeypatch.setattr(fingrid_api.requests, "get", fake_get)
    return calls


@pytest.fixture(autouse=True)
def fast_and_small(monkeypatch):
    """No pauses between requests, and tiny pages so paging is easy to test."""
    monkeypatch.setattr(fingrid_api, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(fingrid_api, "PAGE_SIZE", 3)


def test_keeps_reading_pages_when_reported_total_is_too_low(monkeypatch):
    # The bug found in the real API: 7 rows exist, but the API reports only 6
    # (two full pages). Trusting it would silently lose the 7th row.
    rows = make_rows(7)
    calls = fake_api(monkeypatch, rows, reported_total=6)

    df = fingrid_api._fetch_window(192, "2026-10-06T00:00:00Z",
                                   "2026-10-07T00:00:00Z", headers={})

    assert len(df) == 7
    assert calls == [1, 2, 3]  # kept going until a short page came back


def test_stops_after_a_short_page(monkeypatch):
    calls = fake_api(monkeypatch, make_rows(2), reported_total=2)

    df = fingrid_api._fetch_window(192, "2026-10-06T00:00:00Z",
                                   "2026-10-07T00:00:00Z", headers={})

    assert len(df) == 2
    assert calls == [1]


def test_raises_if_fewer_rows_than_reported(monkeypatch):
    # The reported total can be too low, but never too high: if fewer rows
    # arrive than reported, data was genuinely lost and we must not continue.
    fake_api(monkeypatch, make_rows(2), reported_total=5)

    with pytest.raises(RuntimeError, match="reports at least 5"):
        fingrid_api._fetch_window(192, "2026-10-06T00:00:00Z",
                                  "2026-10-07T00:00:00Z", headers={})


def test_returns_expected_columns_and_types(monkeypatch):
    fake_api(monkeypatch, make_rows(2), reported_total=2)

    df = fingrid_api._fetch_window(192, "2026-10-06T00:00:00Z",
                                   "2026-10-07T00:00:00Z", headers={})

    assert list(df.columns) == ["datasetId", "startTime", "endTime", "value"]
    assert pd.api.types.is_datetime64_any_dtype(df["startTime"])
    assert pd.api.types.is_datetime64_any_dtype(df["endTime"])


def test_long_period_is_split_into_chunks_and_duplicates_dropped(monkeypatch):
    windows = []

    def fake_window(dataset_id, start, end, headers):
        windows.append((start, end))
        # Every chunk returns the same row, so all but one are duplicates
        return pd.DataFrame({
            "datasetId": [192],
            "startTime": [pd.Timestamp("2026-10-06T00:00:00Z")],
            "endTime": [pd.Timestamp("2026-10-06T00:03:00Z")],
            "value": [1.0],
        })

    monkeypatch.setattr(fingrid_api, "_fetch_window", fake_window)

    df = fingrid_api.fetch_dataset(192, "2026-01-01T00:00:00Z",
                                   "2026-03-15T00:00:00Z", headers={})

    # 73 days with 30-day chunks: 30 + 30 + 13
    assert windows == [
        ("2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"),
        ("2026-01-31T00:00:00Z", "2026-03-02T00:00:00Z"),
        ("2026-03-02T00:00:00Z", "2026-03-15T00:00:00Z"),
    ]
    assert len(df) == 1


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("FINGRID_API_KEY", raising=False)

    with pytest.raises(ValueError, match="FINGRID_API_KEY"):
        fingrid_api.get_headers()


def test_api_key_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("FINGRID_API_KEY", "test-key")

    assert fingrid_api.get_headers() == {"x-api-key": "test-key"}
