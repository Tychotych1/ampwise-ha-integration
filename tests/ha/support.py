"""Hulpmiddelen voor de tests met een nagebootste Home Assistant: een testportal (aioclient_mock) en een manier om de tijd te laten verstrijken."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from yarl import URL

from custom_components.ampwise_push.const import (
    CONF_API_KEY,
    CONF_INGEST_URL,
    CONF_PUSH_INTERVAL,
    DOMAIN,
    INTEGRATION_VERSION,
)

PORTAL_URL = "https://portal.test/api/ingest"
# Alleen voor de tests; het formaat van een echte sleutel is "amp_" met daarachter 32 tekens.
PUSH_KEY = "amp_testsleutel_voor_de_tests_0123456789"
INTERVAL = 30


class FakePortal:
    """Een testportal achter aioclient_mock: de standen (mode) en de lijst van gekoppelde sensoren zijn tijdens een test te veranderen.

    mode: "ok" (JSON met mapped), "legacy" (JSON zonder mapped: een oudere portal), "html" (200 met een foutpagina, geen JSON), "401", "426", "500", "refused" (verbinding geweigerd),
    "timeout"."""

    def __init__(self, aioclient_mock: Any, mapped: list[str] | None = None) -> None:
        self.mode = "ok"
        self.mapped: list[str] = list(mapped or [])
        aioclient_mock.post(PORTAL_URL, side_effect=self._handle)

    async def _handle(self, method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        mode = self.mode
        if mode == "refused":
            return AiohttpClientMockResponse(method, url, exc=aiohttp.ClientConnectionError("Cannot connect to host portal.test:443"))
        if mode == "timeout":
            return AiohttpClientMockResponse(method, url, exc=TimeoutError())
        if mode == "html":
            return AiohttpClientMockResponse(method, url, status=200, text="<html><body>Bad gateway (tunnel)</body></html>", headers={"content-type": "text/html"})
        if mode in ("401", "426", "500"):
            return AiohttpClientMockResponse(method, url, status=int(mode), json={"error": mode})
        if mode == "legacy":
            return AiohttpClientMockResponse(method, url, status=200, json={"ok": True, "received": 3, "catalog": 0, "legacy": False})
        return AiohttpClientMockResponse(method, url, status=200, json={"ok": True, "received": 0, "catalog": 0, "mapped": list(self.mapped), "legacy": False})


def make_entry(hass: HomeAssistant, key: str = PUSH_KEY, url: str = PORTAL_URL, interval: int = INTERVAL) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ampwise",
        data={CONF_API_KEY: key, CONF_INGEST_URL: url, CONF_PUSH_INTERVAL: interval},
        unique_id=key[:16],
    )
    entry.add_to_hass(hass)
    return entry


def set_sensor(hass: HomeAssistant, entity_id: str, state: str, **attributes: Any) -> None:
    hass.states.async_set(entity_id, state, attributes)


async def advance(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    """Laat `seconds` seconden verstrijken (klok en timers) en wacht tot alles wat daardoor start klaar is."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def posts(aioclient_mock: Any) -> list[dict[str, Any]]:
    """De berichten die de integratie naar de portal stuurde, in volgorde, als {'body': ..., 'headers': ...}. Alleen POST's."""
    out = []
    for method, url, data, headers in aioclient_mock.mock_calls:
        if method.lower() != "post":
            continue
        body = data if isinstance(data, dict) else json.loads(data)
        out.append({"url": str(url), "body": body, "headers": dict(headers or {})})
    return out


def energy_sensors(hass: HomeAssistant) -> None:
    """Een kleine installatie: drie energiesensoren, een temperatuursensor, een aanwezigheidssensor en een gassensor."""
    set_sensor(hass, "sensor.zon", "1500", unit_of_measurement="W", device_class="power", friendly_name="Zon")
    set_sensor(hass, "sensor.net_kw", "-0.4", unit_of_measurement="kW", device_class="power", friendly_name="Net")
    set_sensor(hass, "sensor.zon_vandaag", "7.2", unit_of_measurement="kWh", device_class="energy", friendly_name="Zon vandaag")
    set_sensor(hass, "sensor.woonkamer_temperatuur", "21.5", unit_of_measurement="°C", device_class="temperature", friendly_name="Woonkamer")
    set_sensor(hass, "sensor.aanwezigheid_tycho", "home", friendly_name="Aanwezigheid Tycho")
    set_sensor(hass, "sensor.gas_vandaag", "3.1", unit_of_measurement="m³", device_class="gas", friendly_name="Gas vandaag")


__all__ = [
    "FakePortal",
    "INTEGRATION_VERSION",
    "INTERVAL",
    "PORTAL_URL",
    "PUSH_KEY",
    "advance",
    "energy_sensors",
    "make_entry",
    "posts",
    "set_sensor",
]
