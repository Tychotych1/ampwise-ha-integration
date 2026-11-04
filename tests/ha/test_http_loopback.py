"""De integratie met ECHTE aiohttp-verbindingen naar een kleine testportal op deze computer (127.0.0.1): dezelfde uitzonderingen en antwoorden als op internet, wat de nagebootste sessie
(aioclient_mock) niet kan geven. Bijvoorbeeld een foutpagina (text/html) die echt een ContentTypeError geeft, een verbinding die geweigerd wordt, en een antwoord dat te lang duurt."""
from __future__ import annotations

import asyncio
import logging
import socket
from datetime import timedelta

import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

import custom_components.ampwise_push as integration
from custom_components.ampwise_push.const import INTEGRATION_VERSION

from support import PUSH_KEY, energy_sensors, make_entry

LOGGER = "custom_components.ampwise_push"


class LocalPortal:
    """Een portal op 127.0.0.1 met een instelbaar gedrag; onthoudt wat hij ontving."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.mapped: list[str] = []
        self.received: list[dict] = []
        self.auth: list[str] = []
        self.delay = 0.0

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.auth.append(request.headers.get("Authorization", ""))
        try:
            self.received.append(await request.json())
        except ValueError:
            self.received.append({"_onleesbaar": True})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.mode == "html":
            return web.Response(text="<html><body>Inloggen bij de wifi</body></html>", content_type="text/html")
        if self.mode in ("401", "426", "500", "502"):
            return web.json_response({"error": self.mode}, status=int(self.mode))
        if self.mode == "legacy":
            return web.json_response({"ok": True, "received": 1})
        return web.json_response({"ok": True, "mapped": self.mapped, "legacy": False})


@pytest.fixture
async def portal(aiohttp_server):
    state = LocalPortal()
    app = web.Application()
    app.router.add_post("/api/ingest", state.handle)
    server = await aiohttp_server(app, host="127.0.0.1")
    state.url = f"http://127.0.0.1:{server.port}/api/ingest"
    return state


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def tick(hass, seconds: float = 31) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


def warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]


async def test_een_volledige_ronde_over_echte_http(hass, portal):
    energy_sensors(hass)
    portal.mapped = ["sensor.zon"]
    entry = make_entry(hass, url=portal.url)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert len(portal.received) == 2
    assert portal.auth == [f"Bearer {PUSH_KEY}"] * 2
    first, second = portal.received
    assert first["version"] == INTEGRATION_VERSION and first["entities"] == []
    assert sorted(c["entityId"] for c in first["catalog"]) == ["sensor.gas_vandaag", "sensor.net_kw", "sensor.zon", "sensor.zon_vandaag"], "energie en gas, niet de temperatuur en de aanwezigheid"
    assert "catalog" not in second
    assert [e["entityId"] for e in second["entities"]] == ["sensor.zon"]
    assert second["entities"][0]["state"] == "1500"


async def test_een_foutpagina_met_status_200_is_een_echte_contenttype_error_en_wist_de_lijst_niet(hass, portal, caplog):
    energy_sensors(hass)
    portal.mapped = ["sensor.zon"]
    entry = make_entry(hass, url=portal.url)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass)  # de lijst van gekoppelde sensoren is bekend
    portal.mode = "html"
    await tick(hass)
    await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    for received in portal.received[-2:]:
        assert [e["entityId"] for e in received["entities"]] == ["sensor.zon"], "de foutpagina verandert niets aan wat er gaat"
    assert warnings(caplog) == [], "een onleesbaar antwoord is op zich geen storing"


@pytest.mark.parametrize("mode, tekst", [("401", "HTTP 401"), ("426", "werk hem bij via HACS"), ("500", "HTTP 500"), ("502", "HTTP 502")])
async def test_statuscodes_geven_een_waarschuwing_geen_crash_en_herstel(hass, portal, caplog, mode, tekst):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    portal.mapped = ["sensor.zon"]
    entry = make_entry(hass, url=portal.url)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass)
    portal.mode = mode
    for _ in range(4):
        await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert len(warnings(caplog)) == 1 and tekst in warnings(caplog)[0], warnings(caplog)
    portal.mode = "ok"
    await tick(hass)
    assert any("verbinding hersteld" in w for w in warnings(caplog))
    assert PUSH_KEY not in caplog.text


async def test_een_geweigerde_verbinding_is_geen_crash_en_herstelt_zodra_de_portal_terug_is(hass, caplog):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    port = free_port()  # er luistert niets op deze poort: de verbinding wordt geweigerd
    entry = make_entry(hass, url=f"http://127.0.0.1:{port}/api/ingest")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(2):  # op Windows duurt een geweigerde verbinding naar 127.0.0.1 ongeveer 2 seconden
        await tick(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert len(warnings(caplog)) == 1 and "kon de lijst met sensoren niet versturen" in warnings(caplog)[0], warnings(caplog)
    # nu komt de portal op die poort en de volgende tick herstelt zonder opnieuw instellen
    state = LocalPortal()
    state.mapped = ["sensor.zon"]
    app = web.Application()
    app.router.add_post("/api/ingest", state.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", port).start()
        await tick(hass)
        await tick(hass)
        assert any("verbinding hersteld" in w for w in warnings(caplog))
        assert "catalog" in state.received[0], "de lijst die nog niet was aangekomen gaat nu eerst"
        assert [e["entityId"] for e in state.received[-1]["entities"]] == ["sensor.zon"]
    finally:
        await runner.cleanup()


async def test_een_antwoord_dat_te_lang_duurt_is_een_echte_time_out_zonder_crash(hass, portal, caplog, monkeypatch):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    monkeypatch.setattr(integration, "REQUEST_TIMEOUT", 0.2)  # in het echt 10 seconden
    portal.delay = 1.0
    entry = make_entry(hass, url=portal.url)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert len(warnings(caplog)) == 1 and "kon de lijst met sensoren niet versturen" in warnings(caplog)[0], warnings(caplog)
    portal.delay = 0
    await tick(hass)
    assert any("verbinding hersteld" in w for w in warnings(caplog))


async def test_een_oude_portal_zonder_lijst_over_echte_http_krijgt_alleen_energiesensoren(hass, portal):
    energy_sensors(hass)
    portal.mode = "legacy"
    entry = make_entry(hass, url=portal.url)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass)
    assert sorted(e["entityId"] for e in portal.received[-1]["entities"]) == ["sensor.gas_vandaag", "sensor.net_kw", "sensor.zon", "sensor.zon_vandaag"], "de energiesensoren, gas ook"
