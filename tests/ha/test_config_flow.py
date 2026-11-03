"""De config flow zoals Home Assistant hem laat doorlopen: formulier, geldige en ongeldige sleutel, een portal die niet antwoordt, een tweede keer dezelfde sleutel."""
from __future__ import annotations

import logging

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.config_entries import ConfigEntryState

from custom_components.ampwise_push.const import (
    CONF_API_KEY,
    CONF_INGEST_URL,
    CONF_PUSH_INTERVAL,
    DEFAULT_INGEST_URL,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    INTEGRATION_VERSION,
)

from support import FakePortal, PORTAL_URL, PUSH_KEY, make_entry, posts, set_sensor

USER_INPUT = {CONF_API_KEY: PUSH_KEY, CONF_INGEST_URL: PORTAL_URL, CONF_PUSH_INTERVAL: 30}


async def start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_het_formulier_vraagt_sleutel_adres_en_interval_met_de_standaardwaarden(hass):
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    schema = result["data_schema"].schema
    fields = {str(key): key for key in schema}
    assert set(fields) == {CONF_API_KEY, CONF_INGEST_URL, CONF_PUSH_INTERVAL}
    assert fields[CONF_INGEST_URL].default() == DEFAULT_INGEST_URL
    assert fields[CONF_PUSH_INTERVAL].default() == DEFAULT_PUSH_INTERVAL
    assert DEFAULT_INGEST_URL == "https://ampwise.nl/api/ingest"


async def test_een_geldige_sleutel_maakt_de_entry_en_de_controle_stuurt_geen_standen(hass, aioclient_mock):
    set_sensor(hass, "sensor.zon", "1500", unit_of_measurement="W", device_class="power")
    FakePortal(aioclient_mock)
    result = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ampwise"
    assert result["data"] == USER_INPUT
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == PUSH_KEY[:16]
    await hass.async_block_till_done()
    sent = posts(aioclient_mock)
    # de controle in het formulier (zonder standen) en daarna, door het laden van de entry, de lijst van sensoren
    assert sent[0]["body"] == {"version": INTEGRATION_VERSION, "entities": []}, "de controle van de sleutel stuurt geen sensoren"
    assert sent[0]["headers"]["Authorization"] == f"Bearer {PUSH_KEY}"
    assert entry.state is ConfigEntryState.LOADED


async def test_een_401_geeft_ongeldige_sleutel_en_er_komt_geen_entry(hass, aioclient_mock):
    portal = FakePortal(aioclient_mock)
    portal.mode = "401"
    result = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize("mode", ["426", "500", "refused", "timeout"])
async def test_een_portal_die_niet_goed_antwoordt_geeft_dezelfde_fout_en_er_komt_geen_entry(hass, aioclient_mock, mode):
    """De tekst van de fout noemt beide mogelijkheden (ongeldige sleutel of portal niet bereikbaar): zie strings.json."""
    portal = FakePortal(aioclient_mock)
    portal.mode = mode
    result = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_na_een_fout_kan_het_formulier_opnieuw_worden_ingevuld(hass, aioclient_mock):
    portal = FakePortal(aioclient_mock)
    portal.mode = "401"
    flow = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}
    portal.mode = "ok"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_een_adres_dat_geen_adres_is_geeft_een_fout_in_het_formulier_en_geen_crash(hass):
    result = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], {**USER_INPUT, CONF_INGEST_URL: "dit is geen adres"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_dezelfde_sleutel_twee_keer_wordt_afgewezen(hass, aioclient_mock):
    FakePortal(aioclient_mock)
    first = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    assert first["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    second = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_een_andere_sleutel_mag_wel_als_tweede_entry(hass, aioclient_mock):
    FakePortal(aioclient_mock)
    await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    other = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], {**USER_INPUT, CONF_API_KEY: "amp_een_andere_sleutel_voor_de_tests_9876"})
    assert other["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


@pytest.mark.parametrize("interval", [0, -5, 1, 4, 3601])
async def test_een_interval_buiten_de_grenzen_wordt_door_het_formulier_geweigerd(hass, aioclient_mock, interval):
    """Een interval van 0 of lager zou de integratie zonder pauze laten sturen."""
    FakePortal(aioclient_mock)
    flow = await start(hass)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(flow["flow_id"], {**USER_INPUT, CONF_PUSH_INTERVAL: interval})
    assert posts(aioclient_mock) == [], "er is niets naar de portal gegaan"
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize("interval", [5, 30, 3600])
async def test_een_interval_binnen_de_grenzen_wordt_geaccepteerd(hass, aioclient_mock, interval):
    FakePortal(aioclient_mock)
    result = await hass.config_entries.flow.async_configure((await start(hass))["flow_id"], {**USER_INPUT, CONF_PUSH_INTERVAL: interval})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PUSH_INTERVAL] == interval


async def test_de_sleutel_komt_niet_in_het_logboek(hass, aioclient_mock, caplog):
    caplog.set_level(logging.DEBUG)
    portal = FakePortal(aioclient_mock)
    portal.mode = "401"
    flow = await start(hass)
    await hass.config_entries.flow.async_configure(flow["flow_id"], USER_INPUT)
    portal.mode = "ok"
    await hass.config_entries.flow.async_configure(flow["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert PUSH_KEY not in caplog.text
