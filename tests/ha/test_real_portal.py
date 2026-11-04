"""De integratie (in een nagebootste Home Assistant) tegen een ECHTE portal-build op deze computer: ontdekkingslijst, koppelen via de portal-API, standen, unavailable, een foute sleutel en een
ingetrokken sleutel (401). Alleen draaien met een lokale testserver met een eigen testdatabase, nooit tegen productie. Zonder de vier omgevingsvariabelen wordt deze test overgeslagen:

  AMPWISE_TEST_PORTAL_URL   bijvoorbeeld http://127.0.0.1:3121
  AMPWISE_TEST_PUSH_KEY     de push-sleutel van de testtenant (uitvoer van: npm run create-tenant -- --email=... --password=... --generate-push-key)
  AMPWISE_TEST_EMAIL        het e-mailadres van die testtenant
  AMPWISE_TEST_PASSWORD     het wachtwoord van die testtenant

De sleutel en het wachtwoord staan nooit in de code of in een bestand: ze komen alleen uit de omgeving van het proces dat de test draait."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any, Awaitable, Callable

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ampwise_push.const import CONF_API_KEY, CONF_INGEST_URL, CONF_PUSH_INTERVAL, DOMAIN

from support import energy_sensors, make_entry, set_sensor

PORTAL = os.environ.get("AMPWISE_TEST_PORTAL_URL", "").rstrip("/")
KEY = os.environ.get("AMPWISE_TEST_PUSH_KEY", "")
EMAIL = os.environ.get("AMPWISE_TEST_EMAIL", "")
PASSWORD = os.environ.get("AMPWISE_TEST_PASSWORD", "")
LOGGER = "custom_components.ampwise_push"

pytestmark = pytest.mark.skipif(not (PORTAL and KEY and EMAIL and PASSWORD), reason="geen testportal opgegeven (AMPWISE_TEST_PORTAL_URL, _PUSH_KEY, _EMAIL, _PASSWORD)")


async def tick(hass, seconds: float = 31) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


async def eventually(check: Callable[[], Awaitable[Any]], what: str, timeout: float = 10.0) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout
    last: Any = None
    while asyncio.get_running_loop().time() < deadline:
        last = await check()
        if last:
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(f"niet gelukt binnen {timeout} s: {what} (laatste uitkomst: {last!r})")


class Portal:
    """De portal-API zoals de browser hem gebruikt (met een eigen sessie, los van Home Assistant)."""

    def __init__(self, session: aiohttp.ClientSession, cookie: str) -> None:
        self.s = session
        self.cookie = {"Cookie": f"session={cookie}"}

    @classmethod
    async def login(cls, session: aiohttp.ClientSession) -> "Portal":
        async with session.post(f"{PORTAL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}) as resp:
            assert resp.status == 200, "inloggen op de testportal"
            return cls(session, resp.cookies["session"].value)

    async def get(self, path: str) -> Any:
        async with self.s.get(f"{PORTAL}{path}", headers=self.cookie) as resp:
            assert resp.status == 200, f"GET {path}: {resp.status}"
            return await resp.json()

    async def put(self, path: str, body: dict) -> None:
        async with self.s.put(f"{PORTAL}{path}", json=body, headers=self.cookie) as resp:
            assert resp.status == 200, f"PUT {path}: {resp.status}"

    async def delete(self, path: str) -> None:
        async with self.s.delete(f"{PORTAL}{path}", headers=self.cookie) as resp:
            assert resp.status == 200, f"DELETE {path}: {resp.status}"

    async def available(self) -> dict[str, dict]:
        data = await self.get("/api/entity-mappings")
        return {e["entityId"]: e for e in data["availableEntities"]}

    async def readings(self) -> dict[str, dict]:
        data = await self.get("/api/dashboard/live")
        return {r["metricKey"]: r for r in data["readings"]}


async def test_een_volledige_ronde_tegen_de_echte_portal(hass, caplog, capsys):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    energy_sensors(hass)
    set_sensor(hass, "sensor.batterij_soc", "63", unit_of_measurement="%", device_class="battery", friendly_name="Batterij")
    set_sensor(hass, "sensor.prijs_ct", "21.5", unit_of_measurement="ct/kWh", friendly_name="Prijs nu")
    url = f"{PORTAL}/api/ingest"

    async with aiohttp.ClientSession() as http:
        portal = await Portal.login(http)

        # 1. Het formulier: een foute sleutel wordt door de echte portal geweigerd, de goede aangenomen.
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        bad = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_API_KEY: "amp_foute_sleutel_voor_de_test", CONF_INGEST_URL: url, CONF_PUSH_INTERVAL: 30}
        )
        assert bad["type"] is FlowResultType.FORM and bad["errors"] == {"base": "invalid_auth"}
        good = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_API_KEY: KEY, CONF_INGEST_URL: url, CONF_PUSH_INTERVAL: 30})
        assert good["type"] is FlowResultType.CREATE_ENTRY
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.state is ConfigEntryState.LOADED

        # 2. De ontdekkingslijst staat in de keuzelijst van de portal: energie wel (ook kW, ct/kWh en gas), de rest niet.
        available = await eventually(lambda: portal.available(), "de keuzelijst bevat de sensoren")
        assert set(available) == {"sensor.zon", "sensor.net_kw", "sensor.zon_vandaag", "sensor.batterij_soc", "sensor.prijs_ct", "sensor.gas_vandaag"}, sorted(available)
        assert available["sensor.net_kw"]["unitOfMeasurement"] == "kW"
        assert available["sensor.prijs_ct"]["unitOfMeasurement"] == "ct/kWh"
        assert available["sensor.gas_vandaag"]["unitOfMeasurement"] == "m³" and available["sensor.gas_vandaag"]["deviceClass"] == "gas"
        for niet in ("sensor.woonkamer_temperatuur", "sensor.aanwezigheid_tycho"):
            assert niet not in available

        # 3. Koppelen via de portal-API. De volgende push heeft het antwoord met de gekoppelde lijst nog niet gehad; de tweede stuurt de standen.
        await portal.put("/api/component-toggles", {"solar": True, "battery": True})
        await portal.put("/api/entity-mappings", {"solar_power_now": "sensor.zon", "battery_soc": "sensor.batterij_soc", "power_now": "sensor.net_kw"})
        await tick(hass)
        await tick(hass)
        readings = await eventually(lambda: _live_has(portal, "solar_power_now", 1500.0), "de stand van de zon staat in de portal")
        assert readings["battery_soc"]["value"] == 63.0
        assert readings["solar_power_now"]["reachable"] is True

        # 4. De portal weet welke versie van de integratie er draait.
        info = (await portal.get("/api/push-key"))["info"]
        assert info["integrationVersion"] == "1.1.0" and info["rejectedAt"] is None

        # 5. unavailable: een vermogen dat uitvalt is 0 W, een batterijstand is geen waarde (null), nooit de laatste waarde.
        set_sensor(hass, "sensor.zon", "unavailable", unit_of_measurement="W", device_class="power", friendly_name="Zon")
        set_sensor(hass, "sensor.batterij_soc", "unknown", unit_of_measurement="%", device_class="battery", friendly_name="Batterij")
        await tick(hass)
        readings = await eventually(lambda: _live_has(portal, "solar_power_now", 0.0), "unavailable wordt 0 W")
        assert readings["battery_soc"]["value"] is None

        # 6. Een sensor in kW: de portal toont de ruwe waarde (-0.4) met de eenheid van de meting (W); een omrekening naar W zit er niet in (zie het rapport).
        net = (await portal.readings())["power_now"]
        with capsys.disabled():
            print(f"\n[echte portal] power_now gekoppeld aan een sensor in kW met stand -0.4: portal toont value={net['value']} unit={net['unit']}")
        assert net["value"] == -0.4

        # 7. De klant trekt de sleutel in: de volgende push krijgt een echte 401, een waarschuwing, geen crash.
        await portal.delete("/api/push-key")
        for _ in range(3):
            await tick(hass)
        assert entry.state is ConfigEntryState.LOADED
        warnings = [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]
        assert len(warnings) == 1 and "HTTP 401" in warnings[0], warnings
        assert KEY not in caplog.text


async def _live_has(portal: Portal, metric: str, value: float) -> dict | None:
    readings = await portal.readings()
    reading = readings.get(metric)
    return readings if reading and reading["value"] == value else None


async def test_een_setup_met_een_foute_sleutel_tegen_de_echte_portal_geeft_een_waarschuwing_en_geen_crash(hass, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    energy_sensors(hass)
    entry = make_entry(hass, key="amp_foute_sleutel_voor_de_test_0000", url=f"{PORTAL}/api/ingest")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    for _ in range(2):
        await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    warnings = [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]
    assert len(warnings) == 1 and "HTTP 401" in warnings[0], warnings
