"""Tests for the async SHMU client (HTTP mocked with aioresponses)."""

import os

import aiohttp
import pytest
from aioresponses import aioresponses
from freezegun import freeze_time

from custom_components.pool_heating import const as C
from custom_components.pool_heating.shmu import ShmuClient, ShmuError

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

# The recorded fixtures are from the 2026-06-01 model runs; the client stamps
# them with datetime.now(), so freeze inside the fixtures' validity window.
FIXTURE_NOW = "2026-06-01 18:00:00+00:00"


def _text(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


@freeze_time(FIXTURE_NOW)
async def test_get_forecast_picks_latest_runs():
    products = {
        "data": [
            {"type": "aladin", "file_link": "aladin/a.json"},
            {"type": "ecmwf", "file_link": "ecmwf/e.json"},
            {"type": "alaef", "file_link": "alaef/x.json"},
        ]
    }
    with aioresponses() as mock:
        mock.get(C.SHMU_PRODUCTS_URL.format(station=31479), payload=products)
        # content_type is deliberately wrong to exercise json(content_type=None)
        mock.get(C.SHMU_DATA_URL.format(file_link="aladin/a.json"),
                 body=_text("aladin.json"), content_type="text/plain")
        mock.get(C.SHMU_DATA_URL.format(file_link="ecmwf/e.json"),
                 body=_text("ecmwf.json"), content_type="text/plain")
        async with aiohttp.ClientSession() as session:
            fc = await ShmuClient(session, 31479).async_get_forecast()
    assert fc.hourly
    assert len(fc.daily) >= 5


async def test_http_error_raises():
    with aioresponses() as mock:
        mock.get(C.SHMU_PRODUCTS_URL.format(station=31479), status=500)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ShmuError):
                await ShmuClient(session, 31479).async_get_forecast()


@freeze_time(FIXTURE_NOW)
async def test_runs_cached_by_link():
    products = {
        "data": [
            {"type": "aladin", "file_link": "aladin/a.json"},
            {"type": "ecmwf", "file_link": "ecmwf/e.json"},
        ]
    }
    with aioresponses() as mock:
        mock.get(C.SHMU_PRODUCTS_URL.format(station=31479), payload=products, repeat=True)
        # each data file registered ONCE: a second GET would raise (proves both
        # runs stay cached — they must not evict each other)
        mock.get(C.SHMU_DATA_URL.format(file_link="aladin/a.json"),
                 body=_text("aladin.json"), content_type="text/plain")
        mock.get(C.SHMU_DATA_URL.format(file_link="ecmwf/e.json"),
                 body=_text("ecmwf.json"), content_type="text/plain")
        async with aiohttp.ClientSession() as session:
            client = ShmuClient(session, 31479)
            await client.async_get_forecast()
            await client.async_get_forecast()  # must hit the cache, not the network
