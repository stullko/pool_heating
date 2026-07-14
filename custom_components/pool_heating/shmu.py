"""Async SHMU NWP forecast client.

Picks the latest ALADIN + ECMWF run for the configured station, downloads the
JSON, and normalizes it. Runs are cached by their `file_link` (run id) so a tick
that fires before a new model run is published does not re-download.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from .const import SHMU_DATA_URL, SHMU_PRODUCTS_URL
from .forecast import NormalizedForecast, build_normalized

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


class ShmuError(Exception):
    """Raised when SHMU data cannot be retrieved or parsed."""


class ShmuClient:
    """Minimal async client for the SHMU NWP JSON API."""

    def __init__(
        self, session: aiohttp.ClientSession, station: int, *, timeout: int = 30
    ) -> None:
        self._session = session
        self._station = station
        self._timeout = timeout
        self._cache: dict[str, dict] = {}  # file_link -> raw field map

    async def async_station_has_products(self) -> bool:
        """Cheap validity check: does the station publish ALADIN or ECMWF?"""
        products = await self._get_json(
            SHMU_PRODUCTS_URL.format(station=self._station)
        )
        return bool(
            self._first_of_type(products, "aladin")
            or self._first_of_type(products, "ecmwf")
        )

    async def async_get_forecast(self) -> NormalizedForecast:
        """Fetch + normalize the latest ALADIN and ECMWF runs."""
        products = await self._get_json(
            SHMU_PRODUCTS_URL.format(station=self._station)
        )
        aladin_link = self._first_of_type(products, "aladin")
        ecmwf_link = self._first_of_type(products, "ecmwf")

        # Drop superseded runs BEFORE fetching — pruning after would let the
        # cache grow without bound while one model's fetch keeps failing.
        current = {aladin_link, ecmwf_link}
        self._cache = {k: v for k, v in self._cache.items() if k in current}

        aladin = await self._get_run(aladin_link) if aladin_link else None
        ecmwf = await self._get_run(ecmwf_link) if ecmwf_link else None
        if aladin is None and ecmwf is None:
            raise ShmuError("no ALADIN or ECMWF product available for station")

        return build_normalized(aladin, ecmwf, datetime.now(UTC))

    @staticmethod
    def _first_of_type(products: object, model_type: str) -> str | None:
        """First entry of a given type is the latest run (per SHMU ordering)."""
        data = products.get("data") if isinstance(products, dict) else None
        if not isinstance(data, list):
            return None
        for entry in data:
            if (
                isinstance(entry, dict)
                and entry.get("type") == model_type
                and entry.get("file_link")
            ):
                return str(entry["file_link"])
        return None

    async def _get_run(self, file_link: str) -> dict:
        if file_link in self._cache:
            return self._cache[file_link]
        raw = await self._get_json(SHMU_DATA_URL.format(file_link=file_link))
        if not isinstance(raw, dict):
            raise ShmuError(f"unexpected payload for run {file_link}")
        self._cache[file_link] = raw
        return raw

    async def _get_json(self, url: str):
        try:
            async with asyncio.timeout(self._timeout):
                resp = await self._session.get(url)
                resp.raise_for_status()
                # SHMU sometimes serves JSON with a non-JSON content-type.
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise ShmuError(f"GET {url} failed: {err}") from err
