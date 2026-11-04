"""De integratie zoals een echte Home Assistant hem laadt: setup, de eerste push met de ontdekkingslijst, het antwoord met de gekoppelde lijst, daarna alleen de gekoppelde sensoren,
en wat er gebeurt bij een onleesbaar antwoord, een 401, een 426 en een portal die niet bereikbaar is. De portal is hier een testportal (support.FakePortal); de berichten zijn dezelfde als
die van de echte integratie, de antwoorden volgen het contract van src/lib/ingestProtocol.ts en tests/pushContract.spec.ts in de portal."""
from __future__ import annotations

import json
import logging

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir

from custom_components.ampwise_push.const import CATALOG_INTERVAL, DOMAIN, INTEGRATION_VERSION, LOG_COOLDOWN_SECONDS

from support import FakePortal, INTERVAL, PORTAL_URL, PUSH_KEY, advance, energy_sensors, make_entry, posts, set_sensor

LOGGER = "custom_components.ampwise_push"


async def setup_entry(hass, aioclient_mock, mapped=None, mode="ok"):
    portal = FakePortal(aioclient_mock, mapped)
    portal.mode = mode
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return portal, entry


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]


# --- setup en de eerste push met de ontdekkingslijst ---------------------------------------------------------------------------------------------------------------------------------


async def test_setup_laadt_de_entry_en_stuurt_meteen_de_lijst_met_energiesensoren_zonder_standen(hass, aioclient_mock):
    energy_sensors(hass)
    portal, entry = await setup_entry(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED
    sent = posts(aioclient_mock)
    assert len(sent) == 1, "bij het opstarten precies een bericht: de lijst"
    body = sent[0]["body"]
    assert sent[0]["url"] == PORTAL_URL
    assert sent[0]["headers"]["Authorization"] == f"Bearer {PUSH_KEY}"
    assert body["version"] == INTEGRATION_VERSION
    assert body["entities"] == [], "de ontdekkingslijst gaat zonder standen"
    ids = sorted(c["entityId"] for c in body["catalog"])
    assert ids == ["sensor.gas_vandaag", "sensor.net_kw", "sensor.zon", "sensor.zon_vandaag"], "kW, W, kWh en gas zijn energie; temperatuur en aanwezigheid niet"
    zon = next(c for c in body["catalog"] if c["entityId"] == "sensor.zon")
    assert zon == {"entityId": "sensor.zon", "unitOfMeasurement": "W", "deviceClass": "power", "friendlyName": "Zon"}
    gas = next(c for c in body["catalog"] if c["entityId"] == "sensor.gas_vandaag")
    assert gas == {"entityId": "sensor.gas_vandaag", "unitOfMeasurement": "m³", "deviceClass": "gas", "friendlyName": "Gas vandaag"}, "een gassensor staat in de ontdekkingslijst, zonder stand"
    dump = json.dumps(body)
    for niet in ("state", "1500", "-0.4", "7.2", "3.1", "21.5", "Woonkamer", "Aanwezigheid", "aanwezigheid", "home"):
        assert niet not in dump, f"{niet!r} mag de catalogus niet in"


async def test_de_nieuwe_eenheden_komen_in_de_lijst_en_gas_ook(hass, aioclient_mock):
    """Gas: het type gas telt in elke eenheid (ook kWh), de eenheid m³ of m3 telt ook zonder type. Bewuste afweging: water in m³ komt door de eenheid ook binnen; water in liters niet."""
    for entity_id, unit, device_class in (
        ("sensor.a_w", "W", None),
        ("sensor.b_kw", "kW", None),
        ("sensor.c_wh", "Wh", None),
        ("sensor.d_kwh", "kWh", None),
        ("sensor.e_mwh", "MWh", None),
        ("sensor.f_pct", "%", None),
        ("sensor.g_eur", "€/kWh", None),
        ("sensor.h_eur", "EUR/kWh", None),
        ("sensor.i_ct", "ct/kWh", None),
        ("sensor.j_mwh", "€/MWh", None),
        ("sensor.k_mwh", "EUR/MWh", None),
        ("sensor.gas_m3", "m³", "gas"),
        ("sensor.gas_m3_zonder_type", "m3", None),
        ("sensor.gas_m3_ascii_met_type", "m3", "gas"),
        ("sensor.gas_kwh", "kWh", "gas"),
        ("sensor.gas_kwh_zonder_type", "kWh", None),
        ("sensor.gas_ft3", "ft³", "gas"),
        ("sensor.gas_zonder_eenheid", None, "gas"),
        ("sensor.water_m3", "m³", "water"),
        ("sensor.water", "L", "water"),
        ("sensor.gas_prijs", "€/m³", None),
        ("sensor.gas_ft3_zonder_type", "ft³", None),
    ):
        attrs = {"unit_of_measurement": unit}
        if device_class:
            attrs["device_class"] = device_class
        set_sensor(hass, entity_id, "1", **attrs)
    await setup_entry(hass, aioclient_mock)
    ids = sorted(c["entityId"] for c in posts(aioclient_mock)[0]["body"]["catalog"])
    assert ids == sorted(
        [
            "sensor.a_w", "sensor.b_kw", "sensor.c_wh", "sensor.d_kwh", "sensor.e_mwh", "sensor.f_pct", "sensor.g_eur", "sensor.h_eur", "sensor.i_ct", "sensor.j_mwh", "sensor.k_mwh",
            "sensor.gas_m3", "sensor.gas_m3_zonder_type", "sensor.gas_m3_ascii_met_type", "sensor.gas_kwh", "sensor.gas_kwh_zonder_type", "sensor.gas_ft3", "sensor.gas_zonder_eenheid", "sensor.water_m3",
        ]
    ), "niet: water in liters, de gasprijs in euro per m³ en een volume in ft³ zonder type gas"


async def test_alleen_sensor_entiteiten_geen_andere_domeinen(hass, aioclient_mock):
    set_sensor(hass, "sensor.zon", "10", unit_of_measurement="W", device_class="power")
    set_sensor(hass, "binary_sensor.kabel", "on", device_class="power")
    set_sensor(hass, "switch.stopcontact", "on", device_class="outlet", unit_of_measurement="W")
    set_sensor(hass, "device_tracker.auto", "home")
    await setup_entry(hass, aioclient_mock)
    assert [c["entityId"] for c in posts(aioclient_mock)[0]["body"]["catalog"]] == ["sensor.zon"]


# --- het antwoord met de gekoppelde lijst, daarna alleen de gekoppelde sensoren -----------------------------------------------------------------------------------------------------


async def test_na_het_antwoord_gaan_alleen_de_gekoppelde_sensoren_mee_met_last_updated_en_versie(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon", "sensor.net_kw"])
    await advance(hass, freezer, INTERVAL + 1)
    sent = posts(aioclient_mock)
    assert len(sent) == 2
    body = sent[1]["body"]
    assert "catalog" not in body, "de lijst gaat niet bij elke push mee"
    assert body["version"] == INTEGRATION_VERSION
    by_id = {e["entityId"]: e for e in body["entities"]}
    assert sorted(by_id) == ["sensor.net_kw", "sensor.zon"], "alleen de gekoppelde sensoren, niet de temperatuur, aanwezigheid, de niet-gekoppelde gassensor of de niet-gekoppelde energiesensor"
    zon = by_id["sensor.zon"]
    assert zon["state"] == "1500"
    assert zon["unitOfMeasurement"] == "W"
    assert zon["deviceClass"] == "power"
    assert zon["friendlyName"] == "Zon"
    assert zon["lastUpdated"] == hass.states.get("sensor.zon").last_updated.isoformat(), "last_updated van Home Assistant, als ISO-tekst"
    assert by_id["sensor.net_kw"]["state"] == "-0.4"
    dump = json.dumps(body)
    for niet in ("Woonkamer", "21.5", "Aanwezigheid", "Gas vandaag", "3.1", "7.2"):
        assert niet not in dump


async def test_een_gekoppelde_gassensor_gaat_met_zijn_stand_mee(hass, aioclient_mock, freezer):
    """Een gassensor (type gas, m³) staat in de ontdekkingslijst (zie de eerste test) en, zodra de klant hem koppelt, met zijn stand in de pushes erna; ook gas in kWh en een gassensor in m3 zonder type."""
    energy_sensors(hass)
    set_sensor(hass, "sensor.gas_kwh", "31.5", unit_of_measurement="kWh", device_class="gas", friendly_name="Gas in kWh")
    set_sensor(hass, "sensor.gas_m3_zonder_type", "2.4", unit_of_measurement="m3", friendly_name="Gas zonder type")
    await setup_entry(hass, aioclient_mock, mapped=["sensor.gas_vandaag", "sensor.gas_kwh", "sensor.gas_m3_zonder_type"])
    await advance(hass, freezer, INTERVAL + 1)
    body = posts(aioclient_mock)[-1]["body"]
    by_id = {e["entityId"]: e for e in body["entities"]}
    assert sorted(by_id) == ["sensor.gas_kwh", "sensor.gas_m3_zonder_type", "sensor.gas_vandaag"]
    gas = by_id["sensor.gas_vandaag"]
    assert (gas["state"], gas["unitOfMeasurement"], gas["deviceClass"], gas["friendlyName"]) == ("3.1", "m³", "gas", "Gas vandaag")
    assert gas["lastUpdated"] == hass.states.get("sensor.gas_vandaag").last_updated.isoformat()
    assert (by_id["sensor.gas_kwh"]["state"], by_id["sensor.gas_kwh"]["unitOfMeasurement"]) == ("31.5", "kWh")
    assert (by_id["sensor.gas_m3_zonder_type"]["state"], by_id["sensor.gas_m3_zonder_type"]["unitOfMeasurement"]) == ("2.4", "m3")


async def test_een_tweede_push_stuurt_de_lijst_niet_opnieuw_maar_de_lijst_komt_na_een_dag_wel_weer(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    for _ in range(3):
        await advance(hass, freezer, INTERVAL)
    sent = posts(aioclient_mock)
    assert len(sent) == 4
    assert "catalog" in sent[0]["body"]
    assert all("catalog" not in s["body"] for s in sent[1:]), "drie pushes na elkaar zonder lijst"
    await advance(hass, freezer, CATALOG_INTERVAL.total_seconds())
    catalogs = [s for s in posts(aioclient_mock) if "catalog" in s["body"]]
    assert len(catalogs) == 2, "na een dag gaat de lijst opnieuw"
    assert catalogs[1]["body"]["entities"] == []


async def test_de_lijst_van_gekoppelde_sensoren_wordt_bij_elk_antwoord_ververst(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)
    assert [e["entityId"] for e in posts(aioclient_mock)[-1]["body"]["entities"]] == ["sensor.zon"]
    portal.mapped = ["sensor.zon", "sensor.zon_vandaag", "sensor.aanwezigheid_tycho"]  # de klant koppelt er twee bij, een ervan zonder type of eenheid
    await advance(hass, freezer, INTERVAL)  # deze push heeft nog de oude lijst, het antwoord brengt de nieuwe
    await advance(hass, freezer, INTERVAL)
    assert sorted(e["entityId"] for e in posts(aioclient_mock)[-1]["body"]["entities"]) == ["sensor.aanwezigheid_tycho", "sensor.zon", "sensor.zon_vandaag"], "wat de klant koppelt komt altijd door"
    portal.mapped = []
    await advance(hass, freezer, INTERVAL)
    await advance(hass, freezer, INTERVAL)
    last = posts(aioclient_mock)[-1]["body"]
    assert last["entities"] == [], "niets gekoppeld: een bericht zonder standen (de portal ziet zo dat de integratie leeft)"
    assert last["version"] == INTEGRATION_VERSION


async def test_een_nieuwe_stand_gaat_mee_en_de_last_updated_verandert_met_de_stand(hass, aioclient_mock, freezer):
    set_sensor(hass, "sensor.zon", "100", unit_of_measurement="W", device_class="power")
    await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)
    first = posts(aioclient_mock)[-1]["body"]["entities"][0]
    set_sensor(hass, "sensor.zon", "250", unit_of_measurement="W", device_class="power")
    await advance(hass, freezer, INTERVAL)
    second = posts(aioclient_mock)[-1]["body"]["entities"][0]
    assert (first["state"], second["state"]) == ("100", "250")
    assert second["lastUpdated"] > first["lastUpdated"]


@pytest.mark.parametrize("value", ["unavailable", "unknown"])
async def test_unavailable_en_unknown_gaan_als_tekst_door_de_portal_maakt_er_geen_waarde_van(hass, aioclient_mock, freezer, value):
    """De portal verwacht de tekst zoals Home Assistant hem geeft (tests/pushContract.spec.ts, 0.4): de integratie laat de sensor niet weg en maakt er geen 0 of null van."""
    set_sensor(hass, "sensor.zon", value, unit_of_measurement="W", device_class="power")
    set_sensor(hass, "sensor.ok", "5", unit_of_measurement="W", device_class="power")
    await setup_entry(hass, aioclient_mock, mapped=["sensor.zon", "sensor.ok"])
    await advance(hass, freezer, INTERVAL)
    entities = {e["entityId"]: e for e in posts(aioclient_mock)[-1]["body"]["entities"]}
    assert entities["sensor.zon"]["state"] == value
    assert entities["sensor.zon"]["lastUpdated"] is not None
    assert entities["sensor.ok"]["state"] == "5"


async def test_een_gekoppelde_sensor_die_niet_meer_bestaat_wordt_overgeslagen(hass, aioclient_mock, freezer):
    set_sensor(hass, "sensor.zon", "100", unit_of_measurement="W", device_class="power")
    await setup_entry(hass, aioclient_mock, mapped=["sensor.zon", "sensor.weg"])
    await advance(hass, freezer, INTERVAL)
    assert [e["entityId"] for e in posts(aioclient_mock)[-1]["body"]["entities"]] == ["sensor.zon"]


# --- een oudere portal en een onleesbaar antwoord ---------------------------------------------------------------------------------------------------------------------------------


async def test_een_oudere_portal_zonder_lijst_krijgt_alleen_de_energiesensoren(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    await setup_entry(hass, aioclient_mock, mode="legacy")
    await advance(hass, freezer, INTERVAL)
    body = posts(aioclient_mock)[-1]["body"]
    assert sorted(e["entityId"] for e in body["entities"]) == ["sensor.gas_vandaag", "sensor.net_kw", "sensor.zon", "sensor.zon_vandaag"], "de energiesensoren, gas ook; niet de temperatuur of de aanwezigheid"
    dump = json.dumps(body)
    for niet in ("Woonkamer", "Aanwezigheid", "21.5"):
        assert niet not in dump


async def test_een_foutpagina_na_een_bekende_lijst_wist_de_lijst_niet(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)  # de lijst is nu bekend
    portal.mode = "html"
    await advance(hass, freezer, INTERVAL)
    await advance(hass, freezer, INTERVAL)
    for sent in posts(aioclient_mock)[-2:]:
        assert [e["entityId"] for e in sent["body"]["entities"]] == ["sensor.zon"], "een tunnel die een foutpagina geeft verandert niets aan wat er gaat"


async def test_een_foutpagina_voor_het_eerste_antwoord_stuurt_geen_standen(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    await setup_entry(hass, aioclient_mock, mode="html")
    await advance(hass, freezer, INTERVAL)
    await advance(hass, freezer, INTERVAL)
    sent = posts(aioclient_mock)
    assert len(sent) == 3
    assert "catalog" in sent[0]["body"]
    for later in sent[1:]:
        assert later["body"]["entities"] == [], "zolang de portal niet heeft gezegd wat hij wil gaat er niets mee"
        assert "catalog" not in later["body"]


# --- 401, 426, 500 en een portal die niet bereikbaar is ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["401", "426", "500", "refused", "timeout", "html"])
async def test_een_storing_bij_het_opstarten_is_geen_crash_en_de_entry_blijft_geladen(hass, aioclient_mock, caplog, mode):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    _, entry = await setup_entry(hass, aioclient_mock, mode=mode)
    assert entry.state is ConfigEntryState.LOADED
    if mode != "html":
        assert len(warnings(caplog)) == 1
        assert "kon de lijst met sensoren niet versturen" in warnings(caplog)[0]
    assert PUSH_KEY not in caplog.text, "de sleutel komt nooit in het logboek"


async def test_een_401_geeft_een_waarschuwing_en_geen_herauthenticatie_en_geen_melding(hass, aioclient_mock, freezer, caplog):
    """Wat de integratie nu doet bij een ingetrokken sleutel (401): een waarschuwing in het logboek, hooguit een per uur. Geen melding in Home Assistant (repair issue) en geen
    herauthenticatie: dat is een bevinding in het rapport, geen fout in de test."""
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    portal, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    portal.mode = "401"
    for _ in range(20):
        await advance(hass, freezer, INTERVAL)
    assert entry.state is ConfigEntryState.LOADED
    assert len(warnings(caplog)) == 1, f"een waarschuwing, geen lawine: {warnings(caplog)}"
    assert "HTTP 401" in warnings(caplog)[0]
    assert PUSH_KEY not in caplog.text
    assert not ir.async_get(hass).issues, "er komt (nog) geen melding in Home Assistant"
    assert hass.config_entries.flow.async_progress() == [], "en geen herauthenticatie"


async def test_een_426_geeft_een_waarschuwing_die_zegt_dat_de_integratie_bijgewerkt_moet_worden(hass, aioclient_mock, freezer, caplog):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    portal, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    portal.mode = "426"
    for _ in range(5):
        await advance(hass, freezer, INTERVAL)
    assert entry.state is ConfigEntryState.LOADED
    assert len(warnings(caplog)) == 1
    assert "werk hem bij via HACS" in warnings(caplog)[0]
    assert not ir.async_get(hass).issues


@pytest.mark.parametrize("mode", ["refused", "timeout"])
async def test_een_portal_die_niet_bereikbaar_is_geeft_een_waarschuwing_geen_lawine_en_herstelt(hass, aioclient_mock, freezer, caplog, mode):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    portal, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)  # de lijst van gekoppelde sensoren is bekend
    before = len(posts(aioclient_mock))
    portal.mode = mode
    for _ in range(30):
        await advance(hass, freezer, INTERVAL)
    assert entry.state is ConfigEntryState.LOADED
    assert len(posts(aioclient_mock)) == before + 30, "elke tick probeert het opnieuw"
    assert len(warnings(caplog)) == 1, f"een waarschuwing in 15 minuten storing: {warnings(caplog)}"
    assert "kon data niet versturen" in warnings(caplog)[0]
    portal.mode = "ok"
    await advance(hass, freezer, INTERVAL)
    assert any("verbinding hersteld" in w for w in warnings(caplog)), "bij herstel een melding"
    assert len([w for w in warnings(caplog) if "verbinding hersteld" in w]) == 1
    assert [e["entityId"] for e in posts(aioclient_mock)[-1]["body"]["entities"]] == ["sensor.zon"], "en het sturen gaat gewoon verder, met dezelfde lijst"
    await advance(hass, freezer, INTERVAL)
    assert len(warnings(caplog)) == 2, "na het herstel geen nieuwe meldingen"


async def test_na_een_uur_storing_komt_er_een_tweede_waarschuwing(hass, aioclient_mock, freezer, caplog):
    energy_sensors(hass)
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    portal, _ = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)
    portal.mode = "refused"
    await advance(hass, freezer, INTERVAL)
    assert len(warnings(caplog)) == 1
    await advance(hass, freezer, LOG_COOLDOWN_SECONDS - INTERVAL - 1)
    assert len(warnings(caplog)) == 1, "binnen het uur geen tweede"
    await advance(hass, freezer, 2 * INTERVAL)
    assert len(warnings(caplog)) == 2, "na een uur nog een, zodat een aanhoudende storing zichtbaar blijft"


async def test_de_portal_was_er_niet_bij_het_opstarten_de_lijst_gaat_bij_de_eerste_push_die_slaagt_en_de_standen_meteen_erachter(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    portal, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"], mode="refused")
    assert entry.state is ConfigEntryState.LOADED
    await advance(hass, freezer, INTERVAL)
    await advance(hass, freezer, INTERVAL)
    sent = posts(aioclient_mock)
    assert len(sent) == 3 and all("catalog" in s["body"] for s in sent), "zolang de lijst niet is aangekomen, probeert elke tick de lijst opnieuw"
    portal.mode = "ok"
    await advance(hass, freezer, INTERVAL)
    sent = posts(aioclient_mock)
    assert "catalog" in sent[3]["body"], "de lijst gaat eerst"
    assert sent[4]["body"]["entities"][0]["entityId"] == "sensor.zon" and "catalog" not in sent[4]["body"], "en in dezelfde tick de standen van de gekoppelde sensor"
    await advance(hass, freezer, INTERVAL)
    assert "catalog" not in posts(aioclient_mock)[-1]["body"]


# --- uitladen en opnieuw laden ----------------------------------------------------------------------------------------------------------------------------------------------------


async def test_uitladen_stopt_het_sturen_en_opnieuw_laden_stuurt_de_lijst_opnieuw(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    portal, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await advance(hass, freezer, INTERVAL)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.data.get(DOMAIN, {}) == {}, "niets blijft hangen"
    count = len(posts(aioclient_mock))
    for _ in range(5):
        await advance(hass, freezer, INTERVAL)
    await advance(hass, freezer, CATALOG_INTERVAL.total_seconds())
    assert len(posts(aioclient_mock)) == count, "na het uitladen gaat er niets meer naar de portal"
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sent = posts(aioclient_mock)
    assert len(sent) == count + 1 and "catalog" in sent[-1]["body"], "opnieuw laden = opnieuw beginnen met de lijst"


async def test_verwijderen_van_de_entry_laadt_uit_en_stopt_de_timers(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    _, entry = await setup_entry(hass, aioclient_mock, mapped=["sensor.zon"])
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    count = len(posts(aioclient_mock))
    await advance(hass, freezer, 10 * INTERVAL)
    assert len(posts(aioclient_mock)) == count


# --- het interval -----------------------------------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stored, effective", [(0, 5), (-5, 5), (1, 5), (30, 30), (999999, 3600)])
async def test_een_opgeslagen_interval_buiten_de_grenzen_wordt_bijgesteld_zodat_er_niet_zonder_pauze_wordt_gestuurd(hass, aioclient_mock, freezer, stored, effective):
    """Een entry die met een oudere versie van het formulier is aangemaakt kan een interval van 0 hebben (dat gaf honderden berichten per seconde)."""
    set_sensor(hass, "sensor.zon", "1", unit_of_measurement="W", device_class="power")
    portal = FakePortal(aioclient_mock, ["sensor.zon"])
    entry = make_entry(hass, interval=stored)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    count = len(posts(aioclient_mock))
    await advance(hass, freezer, effective - 1)
    assert len(posts(aioclient_mock)) == count, "voor het interval om is gaat er niets"
    await advance(hass, freezer, 1)
    assert len(posts(aioclient_mock)) == count + 1, "precies een bericht per interval"
    assert portal.mode == "ok"


# --- een entry van de vorige versie ---------------------------------------------------------------------------------------------------------------------------------------------


async def test_een_entry_die_met_versie_1_0_0_is_aangemaakt_laadt_in_deze_versie_zonder_migratie(hass, aioclient_mock, freezer):
    """In Home Assistant staat nu 1.0.0 (commit e09670c): dezelfde drie gegevens (api_key, ingest_url, push_interval, const.py regel 5-7), dezelfde unique_id (de eerste 16 tekens van de
    sleutel, config_flow.py regel 56) en dezelfde VERSION = 1 van de flow. Daarom hoeft er bij het bijwerken niets te migreren."""
    from homeassistant.config_entries import ConfigEntry
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.ampwise_push.config_flow import AmpwiseConfigFlow

    assert AmpwiseConfigFlow.VERSION == 1
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ampwise",
        version=1,
        data={"api_key": PUSH_KEY, "ingest_url": PORTAL_URL, "push_interval": 30},
        unique_id=PUSH_KEY[:16],
    )
    entry.add_to_hass(hass)
    energy_sensors(hass)
    FakePortal(aioclient_mock, ["sensor.zon"])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert isinstance(entry, ConfigEntry) and entry.state is ConfigEntryState.LOADED
    await advance(hass, freezer, INTERVAL)
    assert [e["entityId"] for e in posts(aioclient_mock)[-1]["body"]["entities"]] == ["sensor.zon"]
