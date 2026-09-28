"""app.services.geocode — server-side Google Geocoding proxy (v1.7)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from unittest.mock import MagicMock, patch  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.services.geocode import GeocodeError, geocode_address  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cache_hit():
    """Redis is mocked to always miss so every test exercises the real
    fetch-and-parse path, not a memoized result from an earlier test."""
    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    with patch("app.services.geocode.get_redis", return_value=fake_redis) as get_redis:
        yield get_redis


def _google_response(status="OK", location_type="ROOFTOP", lat=34.0430, lng=-118.2673):
    if status != "OK":
        body = {"status": status, "results": []}
    else:
        body = {
            "status": "OK",
            "results": [{
                "geometry": {"location": {"lat": lat, "lng": lng}, "location_type": location_type},
                "formatted_address": "1111 S Figueroa St, Los Angeles, CA",
            }],
        }
    return httpx.Response(200, json=body, request=httpx.Request("GET", "https://maps.googleapis.com/x"))


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(GeocodeError, match="not configured"):
        geocode_address("LA Convention Center, Los Angeles, CA")


def test_rooftop_result_is_high_confidence(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.return_value = _google_response(location_type="ROOFTOP")
        result = geocode_address("Intuit Dome, Inglewood, CA")

    assert result.location_type == "ROOFTOP"
    assert result.confidence == "high"
    assert result.lat == 34.0430


def test_approximate_result_is_low_confidence(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.return_value = _google_response(location_type="APPROXIMATE")
        result = geocode_address("Venice Beach, Los Angeles, CA")

    assert result.confidence == "low"


def test_zero_results_raises(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.return_value = _google_response(status="ZERO_RESULTS")
        with pytest.raises(GeocodeError, match="ZERO_RESULTS"):
            geocode_address("Nonexistent Place, Nowhere, CA")


def test_cached_result_skips_http_call(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    fake_redis = MagicMock()
    fake_redis.get.return_value = "34.043\x1f-118.2673\x1fROOFTOP\x1fCached Address"
    with patch("app.services.geocode.get_redis", return_value=fake_redis), patch("httpx.Client") as mock_client_cls:
        result = geocode_address("Some Venue, Los Angeles, CA")

    mock_client_cls.assert_not_called()
    assert result.formatted_address == "Cached Address"
    assert result.confidence == "high"
