"""De prijslijst (integratie 1.2.0) zoals een echte Home Assistant de integratie laadt: de portal noemt in zijn antwoord een priceEntity, de integratie leest daarvan raw_today en raw_tomorrow en stuurt ze mee
in de push (priceForecast): de eerste keer, bij een verandering (hooguit eens per 5 minuten) en daarna hooguit eens per 30 minuten; een oudere portal (zonder priceEntity) krijgt niets extra en de push is dan gelijk aan die van 1.1.0.
De portal is hier een testportal (support.FakePortal)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from custom_components.ampwise_push.const import INTEGRATION_VERSION, PRICE_FEED_MAX_SLOTS, PRICE_FEED_MIN_INTERVAL_SECONDS, PRICE_FEED_RESEND_SECONDS

from support import FakePortal, INTERVAL, advance, energy_sensors, make_entry, posts, set_sensor

PRICE = "sensor.stroomprijs"
AMS = timezone(timedelta(hours=1))


def items(first: datetime, count: int, base: float) -> list[dict]:
    """De attributen zoals de prijssensor ze geeft: een lijst van {start, end, value} met datetime-objecten met verschuiving."""
    return [{"start": first + timedelta(minutes=15 * i), "end": first + timedelta(minutes=15 * (i + 1)), "value": round(base + i / 1000, 6)} for i in range(count)]


def price_sensor(hass, tomorrow_base: float = 0.3, with_lists: bool = True, state: str = "0.2") -> None:
    attrs = {"unit_of_measurement": "EUR/kWh", "device_class": "monetary", "friendly_name": "Stroomprijs"}
    if with_lists:
        attrs["raw_today"] = items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS), 96, 0.2)
        attrs["raw_tomorrow"] = items(datetime(2026, 11, 14, 0, 0, tzinfo=AMS), 96, tomorrow_base)
    set_sensor(hass, PRICE, state, **attrs)


async def setup_entry(hass, aioclient_mock, portal_kwargs=None, mapped=None):
    portal = FakePortal(aioclient_mock, mapped if mapped is not None else [PRICE], **(portal_kwargs or {}))
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return portal, entry


def forecasts(aioclient_mock) -> list[dict]:
    return [p["body"]["priceForecast"] for p in posts(aioclient_mock) if "priceForecast" in p["body"]]


async def test_een_portal_zonder_priceEntity_krijgt_geen_prijslijst_en_de_push_is_gelijk_aan_die_van_1_1_0(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    price_sensor(hass)
    await setup_entry(hass, aioclient_mock)  # het antwoord heeft geen priceEntity: een portal van voor de prijslijst
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    sent = posts(aioclient_mock)
    assert len(sent) == 4, "de lijst bij het opstarten en drie keer de standen"
    for push in sent[1:]:
        assert set(push["body"]) == {"version", "entities"}, "precies de velden van 1.1.0"
        assert push["body"]["version"] == INTEGRATION_VERSION
    assert forecasts(aioclient_mock) == []
    assert "raw_today" not in str(sent), "de attributen van de prijssensor verlaten Home Assistant niet zonder priceEntity"


async def test_priceEntity_null_is_ook_geen_prijslijst(hass, aioclient_mock, freezer):
    price_sensor(hass)
    await setup_entry(hass, aioclient_mock, {"price_entity": None})
    await advance(hass, freezer, INTERVAL + 1)
    assert forecasts(aioclient_mock) == []


async def test_met_priceEntity_gaat_de_lijst_mee_bij_de_eerste_push_en_dan_niet_bij_elke_push(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    price_sensor(hass)
    await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    assert forecasts(aioclient_mock) == [], "de ontdekkingslijst bij het opstarten heeft nog geen prijslijst: de portal moet eerst zeggen welke sensor"
    await advance(hass, freezer, INTERVAL + 1)
    sent = forecasts(aioclient_mock)
    assert len(sent) == 1, "de eerste push na het antwoord"
    feed = sent[0]
    assert feed["entityId"] == PRICE
    assert feed["unitOfMeasurement"] == "EUR/kWh"
    assert feed["attributes"] == "raw_today+raw_tomorrow"
    assert len(feed["slots"]) == 192
    assert feed["slots"][0] == {"start": "2026-11-13T00:00:00+01:00", "value": 0.2}
    assert feed["slots"][96] == {"start": "2026-11-14T00:00:00+01:00", "value": 0.3}
    assert posts(aioclient_mock)[1]["body"]["version"] == INTEGRATION_VERSION
    # de volgende pushes (elke 30 seconden) hebben hem niet meer
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    # en na 30 minuten gaat hij weer mee (zodat een gemiste push geen gat laat), maar dan ook weer niet bij de push erna
    await advance(hass, freezer, PRICE_FEED_RESEND_SECONDS)
    assert len(forecasts(aioclient_mock)) == 2
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2


async def test_een_verandering_gaat_mee_maar_niet_vaker_dan_eens_per_5_minuten(hass, aioclient_mock, freezer):
    price_sensor(hass)
    await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    price_sensor(hass, tomorrow_base=0.55)  # de prijzen van morgen zijn anders (of komen om 14:00 pas)
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "binnen 5 minuten na de vorige lijst wacht een verandering"
    price_sensor(hass, tomorrow_base=0.56)  # een sensor die bij elke tick verandert
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    await advance(hass, freezer, PRICE_FEED_MIN_INTERVAL_SECONDS)
    sent = forecasts(aioclient_mock)
    assert len(sent) == 2, "na 5 minuten gaat de laatste stand van de lijst mee"
    assert sent[1]["slots"][96]["value"] == 0.56
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2, "daarna weer niet"

async def test_een_sensor_zonder_de_attributen_geeft_geen_prijslijst_en_de_rest_van_de_push_blijft(hass, aioclient_mock, freezer):
    energy_sensors(hass)
    price_sensor(hass, with_lists=False)
    await setup_entry(hass, aioclient_mock, {"price_entity": PRICE}, mapped=["sensor.zon", PRICE])
    await advance(hass, freezer, INTERVAL + 1)
    assert forecasts(aioclient_mock) == []
    body = posts(aioclient_mock)[1]["body"]
    assert sorted(e["entityId"] for e in body["entities"]) == [PRICE, "sensor.zon"], "de standen gaan gewoon mee"


async def test_na_een_weigering_van_de_portal_gaat_de_volgende_push_zonder_lijst_en_komt_ze_later_terug(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    portal.mode = "500"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "de integratie probeerde hem te sturen en de portal antwoordde niet met 200"
    portal.mode = "ok"
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "dezelfde lijst wordt niet elke tick opnieuw gestuurd"
    # een verandering komt na 5 minuten weer mee, en anders komt dezelfde lijst na 30 minuten terug
    price_sensor(hass, tomorrow_base=0.6)
    await advance(hass, freezer, PRICE_FEED_MIN_INTERVAL_SECONDS)
    assert len(forecasts(aioclient_mock)) == 2
    await advance(hass, freezer, PRICE_FEED_RESEND_SECONDS)
    assert len(forecasts(aioclient_mock)) == 3


async def test_een_verbinding_die_niet_lukte_telt_niet_als_verstuurd_en_wordt_met_wachttijd_opnieuw_geprobeerd(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    portal.mode = "refused"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "de integratie probeerde hem te sturen"
    portal.mode = "ok"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "dezelfde lijst niet bij de volgende tick (31 seconden later): eerst een minuut wachten"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2, "na een minuut een nieuwe poging: de portal heeft niets gezien en nu komt hij aan"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2, "aangekomen: geen herhaling"


async def test_een_lijst_die_steeds_mislukt_wacht_steeds_langer_en_maakt_de_lijsten_per_uur_van_de_portal_niet_op(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    portal.mode = "timeout"  # de portal verwerkt de push misschien wel, maar het antwoord komt niet aan
    attempts = []
    for _ in range(int(3600 / (INTERVAL + 1))):  # een uur aan ticks
        before = len(forecasts(aioclient_mock))
        await advance(hass, freezer, INTERVAL + 1)
        if len(forecasts(aioclient_mock)) > before:
            attempts.append(len(posts(aioclient_mock)))
    assert 2 <= len(forecasts(aioclient_mock)) <= 7, "een uur lang hooguit enkele pogingen (een minuut, twee, vier, acht en zestien minuten wachten), niet bij elke tick (116 ticks)"
    # de tussenpozen worden steeds groter
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    assert gaps == sorted(gaps) and gaps[-1] > gaps[0], f"steeds langer wachten: {gaps}"
    # en zodra de portal weer antwoordt komt de lijst aan en blijft het stil
    portal.mode = "ok"
    delivered = len(forecasts(aioclient_mock))
    for _ in range(int(PRICE_FEED_RESEND_SECONDS / (INTERVAL + 1)) + 2):
        await advance(hass, freezer, INTERVAL + 1)
        if len(forecasts(aioclient_mock)) > delivered:
            break
    assert len(forecasts(aioclient_mock)) == delivered + 1
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == delivered + 1


async def test_na_een_geslaagde_lijst_begint_de_wachttijd_weer_bij_een_minuut(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    portal.mode = "refused"
    await advance(hass, freezer, INTERVAL + 1)  # poging 1 mislukt: een minuut wachten
    await advance(hass, freezer, INTERVAL + 1)
    await advance(hass, freezer, INTERVAL + 1)  # poging 2 mislukt: twee minuten wachten
    assert len(forecasts(aioclient_mock)) == 2
    portal.mode = "ok"
    for _ in range(5):  # de wachttijd van twee minuten om, de lijst komt aan
        await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 3
    # een nieuwe verandering, en nu mislukt de verbinding weer: de wachttijd begint opnieuw bij een minuut (niet bij vier)
    price_sensor(hass, tomorrow_base=0.77)
    portal.mode = "refused"
    await advance(hass, freezer, PRICE_FEED_MIN_INTERVAL_SECONDS)
    assert len(forecasts(aioclient_mock)) == 4
    portal.mode = "ok"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 4, "31 seconden later nog niet"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 5, "na een minuut wel: de teller van mislukkingen was na de geslaagde lijst weer op nul"

async def test_een_antwoord_dat_niet_te_lezen_is_telt_als_niet_aangekomen_en_wordt_met_wachttijd_opnieuw_geprobeerd(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    portal.mode = "html"  # een 200 met een foutpagina van de tunnel: de portal heeft de push niet gezien
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    portal.mode = "ok"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "niet bij de volgende tick"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2, "na een minuut wel, en nu komt hij aan"
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2

async def test_zegt_de_portal_dat_er_geen_prijssensor_is_dan_stopt_het_en_daarna_begint_het_meteen_opnieuw(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    portal.price_entity = None  # de klant ontkoppelt de prijssensor
    await advance(hass, freezer, INTERVAL + 1)  # deze push zegt het nog niet: het antwoord erop wel
    await advance(hass, freezer, INTERVAL + 1)
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1, "geen nieuwe lijst zolang er geen prijssensor is"
    portal.price_entity = PRICE  # weer gekoppeld, dezelfde inhoud: meteen weer mee, niet pas na 30 minuten
    await advance(hass, freezer, INTERVAL + 1)  # het antwoord van deze push noemt de sensor weer
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 2


async def test_een_onleesbaar_antwoord_laat_de_prijssensor_staan_en_een_oudere_portal_zet_hem_uit(hass, aioclient_mock, freezer):
    price_sensor(hass)
    portal, _ = await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1
    portal.mode = "html"  # een foutpagina van de tunnel: zegt niets over de portal
    price_sensor(hass, tomorrow_base=0.7)
    await advance(hass, freezer, PRICE_FEED_MIN_INTERVAL_SECONDS)
    assert len(forecasts(aioclient_mock)) == 2, "de sensor is nog bekend: een verandering gaat mee"
    portal.mode = "legacy"  # een leesbaar antwoord zonder priceEntity: een oudere portal
    await advance(hass, freezer, INTERVAL + 1)
    price_sensor(hass, tomorrow_base=0.8)
    await advance(hass, freezer, PRICE_FEED_MIN_INTERVAL_SECONDS)
    assert len(forecasts(aioclient_mock)) == 2, "een oudere portal krijgt niets extra"


async def test_een_prijssensor_die_niet_bestaat_in_home_assistant_geeft_geen_fout(hass, aioclient_mock, freezer):
    await setup_entry(hass, aioclient_mock, {"price_entity": "sensor.bestaat_niet"}, mapped=[])
    await advance(hass, freezer, INTERVAL + 1)
    assert forecasts(aioclient_mock) == []
    assert len(posts(aioclient_mock)) == 2, "de push zelf gaat gewoon door"


async def test_een_fout_in_het_prijsdeel_stopt_de_gewone_push_nooit(hass, aioclient_mock, freezer, caplog):
    energy_sensors(hass)
    price_sensor(hass)
    await setup_entry(hass, aioclient_mock, {"price_entity": PRICE}, mapped=["sensor.zon", PRICE])
    with patch("custom_components.ampwise_push.price_forecast_to_send", side_effect=RuntimeError("boem: geheime inhoud 0.4321")):
        await advance(hass, freezer, INTERVAL + 1)
        await advance(hass, freezer, INTERVAL + 1)
    sent = posts(aioclient_mock)
    assert len(sent) == 3, "de gewone pushes gaan door"
    for push in sent[1:]:
        assert "priceForecast" not in push["body"]
        assert sorted(e["entityId"] for e in push["body"]["entities"]) == [PRICE, "sensor.zon"]
    meldingen = [r.getMessage() for r in caplog.records if r.name == "custom_components.ampwise_push" and r.levelno >= logging.WARNING and "prijslijst" in r.getMessage()]
    assert len(meldingen) == 1, "een melding per uur, niet per tick"
    assert "RuntimeError" in meldingen[0]
    assert "geheime" not in meldingen[0], "alleen het soort fout, nooit de inhoud"
    # zodra het weer werkt gaat de lijst gewoon mee
    await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1


async def test_een_geheel_getal_boven_1e308_in_de_lijst_stopt_de_push_niet(hass, aioclient_mock, freezer):
    price_sensor(hass)
    attrs = {"unit_of_measurement": "EUR/kWh", "raw_today": items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS), 4, 0.2)}
    attrs["raw_today"].append({"start": datetime(2026, 11, 13, 1, 0, tzinfo=AMS), "end": datetime(2026, 11, 13, 1, 15, tzinfo=AMS), "value": 10**400})
    set_sensor(hass, PRICE, "0.2", **attrs)
    await setup_entry(hass, aioclient_mock, {"price_entity": PRICE})
    await advance(hass, freezer, INTERVAL + 1)
    sent = forecasts(aioclient_mock)
    assert len(sent) == 1, "de push met de lijst is gewoon verstuurd"
    assert len(sent[0]["slots"]) == 4, "het onbruikbare item is overgeslagen"


# --- de Zonneplan-integratie: het attribuut forecast in plaats van raw_today en raw_tomorrow ---

ZP = "sensor.zonneplan_current_quarter_hourly_electricity_tariff"
ZP_GAS = "sensor.zonneplan_current_tariff_gas"
ZP_LITERAL = {
    "start_date": "2026-11-14T07:45:00+01:00",
    "end_date": "2026-11-14T08:00:00+01:00",
    "price_tax_included": {"amount": 4085419},
    "price_tax_excluded": {"amount": 2976938},
    "sustainability_score": {"permille": 169},
}


def zonneplan_items(count: int = 164) -> list[dict]:
    """Het attribuut forecast zoals de Zonneplan-integratie het geeft: aaneengesloten kwartieren vanaf gisteren 07:00 tot het einde van vandaag, bedragen in 1e-7 euro per kWh; het item van 14 november 07:45 is de letterlijke vorm."""
    first = datetime(2026, 11, 13, 7, 0, tzinfo=AMS)
    out = []
    for i in range(count):
        start = first + timedelta(minutes=15 * i)
        out.append(
            {
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(minutes=15)).isoformat(),
                "price_tax_included": {"amount": 3_000_000 + 1000 * i},
                "price_tax_excluded": {"amount": 2_000_000 + 1000 * i},
                "sustainability_score": {"permille": 169},
            }
        )
    if count > 99:
        out[99] = dict(ZP_LITERAL)
    return out


def zonneplan_sensor(hass) -> None:
    set_sensor(hass, ZP, "0.4085419", unit_of_measurement="€/kWh", friendly_name="Huidig kwartier elektriciteitstarief", forecast=zonneplan_items())


async def test_de_prijssensor_van_de_zonneplan_integratie_gaat_mee_als_de_portal_hem_noemt(hass, aioclient_mock, freezer):
    zonneplan_sensor(hass)
    await setup_entry(hass, aioclient_mock, {"price_entity": ZP}, mapped=[ZP])
    await advance(hass, freezer, INTERVAL + 1)
    sent = forecasts(aioclient_mock)
    assert len(sent) == 1
    feed = sent[0]
    assert feed["entityId"] == ZP
    assert feed["unitOfMeasurement"] == "EUR/kWh", "de sensor zegt €/kWh, de portal krijgt EUR/kWh"
    assert feed["attributes"] == "forecast"
    assert len(feed["slots"]) == 164
    assert feed["slots"][0] == {"start": "2026-11-13T07:00:00+01:00", "value": 0.3}
    assert feed["slots"][99] == {"start": "2026-11-14T07:45:00+01:00", "value": 0.4085419}
    assert "price_tax" not in str(feed), "alleen begintijd en prijs"
    # de stand zelf gaat gewoon mee, met de eenheid zoals de sensor hem noemt, en zonder zijn attributen
    entities = posts(aioclient_mock)[1]["body"]["entities"]
    assert [e["entityId"] for e in entities] == [ZP]
    assert entities[0]["state"] == "0.4085419"
    assert entities[0]["unitOfMeasurement"] == "€/kWh"
    assert "price_tax" not in str(entities)
    # en daarna niet bij elke push
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert len(forecasts(aioclient_mock)) == 1


async def test_de_gassensor_van_de_zonneplan_integratie_met_een_item_van_24_uur_gaat_nooit_mee(hass, aioclient_mock, freezer):
    gas = [{"start_date": "2026-11-14T06:00:00+01:00", "end_date": "2026-11-15T06:00:00+01:00", "price_tax_included": {"amount": 12345670}, "price_tax_excluded": {"amount": 9000000}}]
    set_sensor(hass, ZP_GAS, "1.234567", unit_of_measurement="EUR/kWh", forecast=gas)
    await setup_entry(hass, aioclient_mock, {"price_entity": ZP_GAS}, mapped=[ZP_GAS])
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert forecasts(aioclient_mock) == []
    assert len(posts(aioclient_mock)) == 4, "de gewone pushes gaan door"


async def test_zonder_priceEntity_verlaat_de_forecast_van_de_zonneplan_sensor_het_huis_niet(hass, aioclient_mock, freezer):
    zonneplan_sensor(hass)
    await setup_entry(hass, aioclient_mock, mapped=[ZP])  # het antwoord heeft geen priceEntity
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    sent = posts(aioclient_mock)
    assert len(sent) == 4
    for push in sent[1:]:
        assert set(push["body"]) == {"version", "entities"}, "precies de velden van 1.1.0"
    assert forecasts(aioclient_mock) == []
    assert "price_tax" not in str(sent)
    assert "start_date" not in str(sent)


async def test_een_forecast_langer_dan_de_grens_van_de_portal_gaat_afgekapt_op_288_slots_mee(hass, aioclient_mock, freezer):
    """De portal weigert bij meer dan 288 slots de hele lijst: de integratie stuurt er nooit meer, ook niet met een sensor die er 400 geeft."""
    assert PRICE_FEED_MAX_SLOTS == 288
    set_sensor(hass, ZP, "0.4085419", unit_of_measurement="€/kWh", friendly_name="Huidig kwartier elektriciteitstarief", forecast=zonneplan_items(400))
    await setup_entry(hass, aioclient_mock, {"price_entity": ZP}, mapped=[ZP])
    await advance(hass, freezer, INTERVAL + 1)
    sent = forecasts(aioclient_mock)
    assert len(sent) == 1
    assert len(sent[0]["slots"]) == 288
    assert sent[0]["slots"][0] == {"start": "2026-11-13T07:00:00+01:00", "value": 0.3}


async def _lijst_die_de_portal_altijd_weigert_gaat_niet_mee(hass, aioclient_mock, freezer, forecast) -> None:
    """Elke weigering telt voor de bewaking van de prijslijst in de portal: zo'n lijst gaat niet mee, en de gewone push (de stand van de sensor) blijft gewoon doorgaan."""
    set_sensor(hass, ZP, "0.4085419", unit_of_measurement="€/kWh", forecast=forecast)
    await setup_entry(hass, aioclient_mock, {"price_entity": ZP}, mapped=[ZP])
    for _ in range(3):
        await advance(hass, freezer, INTERVAL + 1)
    assert forecasts(aioclient_mock) == []
    assert len(posts(aioclient_mock)) == 4, "de gewone pushes gaan door"
    assert [e["entityId"] for e in posts(aioclient_mock)[1]["body"]["entities"]] == [ZP]


async def test_een_forecast_van_een_slot_gaat_niet_mee_en_de_push_gaat_door(hass, aioclient_mock, freezer):
    await _lijst_die_de_portal_altijd_weigert_gaat_niet_mee(hass, aioclient_mock, freezer, zonneplan_items(1))


async def test_een_forecast_met_een_begintijd_naast_het_kwartier_gaat_niet_mee_en_de_push_gaat_door(hass, aioclient_mock, freezer):
    shifted = [
        {
            **item,
            "start_date": (datetime.fromisoformat(item["start_date"]) + timedelta(minutes=7)).isoformat(),
            "end_date": (datetime.fromisoformat(item["end_date"]) + timedelta(minutes=7)).isoformat(),
        }
        for item in zonneplan_items(20)
    ]
    await _lijst_die_de_portal_altijd_weigert_gaat_niet_mee(hass, aioclient_mock, freezer, shifted)

