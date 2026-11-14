"""Tests voor de berichten naar de portal (payload.py). Draaien zonder Home Assistant: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import unittest
from datetime import datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "ampwise_push"
spec = importlib.util.spec_from_file_location("ampwise_payload", ROOT / "payload.py")
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)
const_spec = importlib.util.spec_from_file_location("ampwise_const", ROOT / "const.py")
const = importlib.util.module_from_spec(const_spec)
const_spec.loader.exec_module(const)

PREFIX = "sensor."


def state(entity_id, value="1", last_updated=None, **attrs):
    return SimpleNamespace(entity_id=entity_id, state=value, attributes=attrs, last_updated=last_updated)


STATES = [
    state("sensor.zon", "1500", datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc), unit_of_measurement="W", device_class="power", friendly_name="Zon"),
    state("sensor.telefoon_batterij", "63", unit_of_measurement="%", device_class="battery", friendly_name="iPhone van Tycho"),
    state("device_tracker.auto", "home"),
    state("binary_sensor.kabel", "on"),
    state("sensor.stuk", "unavailable"),
    state("sensor.woonkamer_temperatuur", "21.5", unit_of_measurement="°C", device_class="temperature", friendly_name="Woonkamer"),
    state("sensor.aanwezigheid_tycho", "home", friendly_name="Aanwezigheid Tycho"),
]


class CatalogTests(unittest.TestCase):
    def test_alleen_energiesensoren_en_nooit_een_stand(self):
        catalog = payload.build_catalog(STATES, PREFIX)
        self.assertEqual([c["entityId"] for c in catalog], ["sensor.zon", "sensor.telefoon_batterij"])
        for entry in catalog:
            self.assertNotIn("state", entry)
            self.assertNotIn("lastUpdated", entry)
        dump = json.dumps(catalog)
        self.assertNotIn('"state"', dump)
        self.assertNotIn("1500", dump)

    def test_naam_type_en_eenheid(self):
        zon = payload.build_catalog(STATES, PREFIX)[0]
        self.assertEqual(zon, {"entityId": "sensor.zon", "unitOfMeasurement": "W", "deviceClass": "power", "friendlyName": "Zon"})

    def test_wat_niet_over_energie_gaat_verlaat_home_assistant_niet(self):
        dump = json.dumps(payload.build_catalog(STATES, PREFIX))
        for niet in ("temperatuur", "Woonkamer", "aanwezigheid", "Aanwezigheid", "sensor.stuk"):
            self.assertNotIn(niet, dump)


class EnergyRelevanceTests(unittest.TestCase):
    def test_de_lijsten_zijn_die_van_de_privacypagina(self):
        self.assertEqual(payload.ENERGY_DEVICE_CLASSES, ("power", "energy", "battery", "voltage", "current", "monetary", "gas"))
        self.assertEqual(payload.ENERGY_UNITS, ("W", "kW", "Wh", "kWh", "MWh", "%", "€/kWh", "EUR/kWh", "ct/kWh", "€/MWh", "EUR/MWh", "m³", "m3"))

    def test_gas_hoort_erbij(self):
        self.assertIn("gas", payload.ENERGY_DEVICE_CLASSES)
        for volume_unit in ("m³", "m3"):
            self.assertIn(volume_unit, payload.ENERGY_UNITS)
        for other in ("water", "volume", "volume_storage"):
            self.assertNotIn(other, payload.ENERGY_DEVICE_CLASSES)
        for volume_unit in ("ft³", "CCF", "L", "€/m³"):
            self.assertNotIn(volume_unit, payload.ENERGY_UNITS)

    def test_dezelfde_gevallen_als_in_de_portal(self):
        """Dezelfde tabel als in de tests van de portal (de gas-gevallen): het type gas telt in elke eenheid, de eenheid m³ of m3 telt ook zonder type."""
        nbsp = "\u00a0"
        cases = [
            ("gas", None, True),
            ("gas", "m³", True),
            ("gas", "m3", True),
            ("gas", "kWh", True),  # gas in kWh met type
            (None, "kWh", True),  # gas in kWh zonder type: de eenheid kWh was er al
            ("gas", "ft³", True),
            ("gas", "CCF", True),
            ("gas", "L", True),
            ("gas", "MJ", True),
            (" gas ", None, True),
            ("\tgas\n", "m³", True),
            (None, "m³", True),
            (None, "m3", True),
            (None, " m³\t", True),
            (None, "\tm3\n", True),
            ("temperature", "m³", True),
            ("Gas", None, False),
            ("GAS", None, False),
            (None, "M3", False),
            (None, "m^3", False),
            (None, "m²", False),
            (None, "ft³", False),
            (None, "CCF", False),
            (None, "L", False),
            (None, "€/m³", False),
            (None, "m³/h", False),
            (None, nbsp + "m³", False),
            (nbsp + "gas", None, False),
            # bewuste afweging: water in m³ komt door de eenheid m³ ook binnen, water in liters niet
            ("water", "m³", True),
            ("water", "m3", True),
            ("water", "L", False),
            ("water", None, False),
            ("volume", "L", False),
            ("volume_storage", "ft³", False),
        ]
        for device_class, unit, expected in cases:
            self.assertEqual(payload.is_energy_relevant(device_class, unit), expected, f"{device_class!r}/{unit!r}")

    def test_geen_eenheid_of_type_dubbel(self):
        self.assertEqual(len(set(payload.ENERGY_UNITS)), len(payload.ENERGY_UNITS))
        self.assertEqual(len(set(payload.ENERGY_DEVICE_CLASSES)), len(payload.ENERGY_DEVICE_CLASSES))

    def test_type_of_eenheid_is_genoeg(self):
        for device_class in ("power", "energy", "battery", "voltage", "current", "monetary"):
            self.assertTrue(payload.is_energy_relevant(device_class, None), device_class)
        for unit in payload.ENERGY_UNITS:
            self.assertTrue(payload.is_energy_relevant(None, unit), unit)
        for unit in ("W", "kW", "Wh", "kWh", "MWh", "%", "€/kWh", "EUR/kWh", "ct/kWh", "€/MWh", "EUR/MWh"):
            self.assertTrue(payload.is_energy_relevant(None, unit), unit)
        self.assertTrue(payload.is_energy_relevant("power", "kW"))
        self.assertTrue(payload.is_energy_relevant(" power ", None))

    def test_al_het_andere_niet(self):
        for device_class, unit in (("temperature", "°C"), ("humidity", None), (None, None), ("", ""), (None, "A"), (None, "V"), ("enum", None), (None, "lx")):
            self.assertFalse(payload.is_energy_relevant(device_class, unit), f"{device_class}/{unit}")

    def test_alleen_ascii_witruimte_valt_weg_zoals_in_de_portal(self):
        self.assertTrue(payload.is_energy_relevant("\tenergy\n", None))
        self.assertTrue(payload.is_energy_relevant(None, " W "))
        self.assertFalse(payload.is_energy_relevant(None, "\u00a0W"))  # een vaste spatie is geen gewone spatie: niet raden
        self.assertFalse(payload.is_energy_relevant("\u00a0power", None))
        self.assertTrue(payload.is_energy_relevant(None, " kW\t"))
        self.assertTrue(payload.is_energy_relevant(None, "\tct/kWh\n"))
        self.assertFalse(payload.is_energy_relevant(None, "\u00a0kW"))
        self.assertFalse(payload.is_energy_relevant(" kW\t", None), "kW is een eenheid, geen type")

    def test_hoofdletters_tellen(self):
        self.assertFalse(payload.is_energy_relevant("Power", None))
        self.assertFalse(payload.is_energy_relevant(None, "w"))
        self.assertFalse(payload.is_energy_relevant(None, "KWH"))
        for unit in ("KW", "mwh", "CT/kWh", "eur/mwh", "Ct/kWh"):
            self.assertFalse(payload.is_energy_relevant(None, unit), unit)

    def test_een_waarde_die_geen_tekst_is_geeft_geen_fout(self):
        self.assertFalse(payload.is_energy_relevant(5, 7))
        self.assertTrue(payload.is_energy_relevant(None, "W"))


class StatesTests(unittest.TestCase):
    def test_alleen_de_gekoppelde_sensoren(self):
        sent = payload.build_states(STATES, {"sensor.zon"}, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], ["sensor.zon"])
        self.assertEqual(sent[0]["state"], "1500")
        self.assertEqual(sent[0]["unitOfMeasurement"], "W")

    def test_elke_stand_heeft_zijn_last_updated(self):
        sent = payload.build_states(STATES, {"sensor.zon", "sensor.stuk"}, PREFIX)
        self.assertEqual(sent[0]["lastUpdated"], "2026-11-03T10:00:00+00:00")
        self.assertIsNone(sent[1]["lastUpdated"])  # geen last_updated bekend

    def test_niets_gekoppeld_geeft_een_lege_lijst(self):
        self.assertEqual(payload.build_states(STATES, set(), PREFIX), [])

    def test_een_portal_zonder_lijst_krijgt_alleen_de_energiesensoren(self):
        sent = payload.build_states(STATES, None, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], ["sensor.zon", "sensor.telefoon_batterij"])
        dump = json.dumps(sent)
        for niet in ("temperatuur", "Woonkamer", "aanwezigheid", "sensor.stuk"):
            self.assertNotIn(niet, dump)

    def test_wat_de_klant_koppelt_komt_altijd_door_ook_zonder_type_of_eenheid(self):
        sent = payload.build_states(STATES, {"sensor.aanwezigheid_tycho"}, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], ["sensor.aanwezigheid_tycho"])

    def test_een_onbekende_gekoppelde_sensor_wordt_overgeslagen(self):
        self.assertEqual(payload.build_states(STATES, {"sensor.bestaat_niet"}, PREFIX), [])


class ParseMappedTests(unittest.TestCase):
    def test_de_lijst_uit_het_antwoord(self):
        self.assertEqual(payload.parse_mapped({"ok": True, "mapped": ["sensor.a", "sensor.b"]}), {"sensor.a", "sensor.b"})
        self.assertEqual(payload.parse_mapped({"ok": True, "mapped": []}), set())

    def test_geen_lijst_betekent_een_oudere_portal(self):
        self.assertIsNone(payload.parse_mapped({"ok": True, "received": 3}))
        self.assertIsNone(payload.parse_mapped(None))
        self.assertIsNone(payload.parse_mapped("tekst"))
        self.assertIsNone(payload.parse_mapped({"mapped": "sensor.a"}))

    def test_rommel_in_de_lijst_wordt_genegeerd(self):
        self.assertEqual(payload.parse_mapped({"mapped": ["sensor.a", 5, None]}), {"sensor.a"})


class UpdateMappedTests(unittest.TestCase):
    def test_een_lijst_in_het_antwoord_wordt_de_nieuwe_lijst(self):
        self.assertEqual(payload.update_mapped(None, False, {"mapped": ["sensor.a"]}), ({"sensor.a"}, False))
        self.assertEqual(payload.update_mapped({"sensor.oud"}, False, {"mapped": []}), (set(), False))
        self.assertEqual(payload.update_mapped(None, True, {"mapped": ["sensor.a"]}), ({"sensor.a"}, False), "een portal die nu wel een lijst geeft is niet meer 'oud'")

    def test_json_zonder_lijst_is_een_oudere_portal(self):
        self.assertEqual(payload.update_mapped(None, False, {"ok": True, "received": 3}), (None, True))
        self.assertEqual(payload.update_mapped({"sensor.a"}, False, {"ok": True}), (None, True))

    def test_een_onleesbaar_antwoord_laat_wat_we_wisten_staan(self):
        for rommel in (None, "<html>Fout</html>", 502, [], ["mapped"]):
            self.assertEqual(payload.update_mapped({"sensor.a"}, False, rommel), ({"sensor.a"}, False), repr(rommel))
            self.assertEqual(payload.update_mapped(None, False, rommel), (None, False), repr(rommel))
            self.assertEqual(payload.update_mapped(None, True, rommel), (None, True), repr(rommel))


class StatesToSendTests(unittest.TestCase):
    def test_met_een_bekende_lijst_alleen_de_gekoppelde(self):
        sent = payload.states_to_send(STATES, {"sensor.zon"}, False, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], ["sensor.zon"])

    def test_een_oudere_portal_krijgt_alleen_de_energiesensoren(self):
        sent = payload.states_to_send(STATES, None, True, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], ["sensor.zon", "sensor.telefoon_batterij"])
        self.assertNotIn("Woonkamer", json.dumps(sent))

    def test_zolang_de_portal_niet_heeft_gezegd_wat_hij_wil_gaat_er_niets_mee(self):
        self.assertEqual(payload.states_to_send(STATES, None, False, PREFIX), [])

    def test_een_foutpagina_na_een_bekende_lijst_verandert_niets_aan_wat_er_gaat(self):
        mapped, legacy = payload.update_mapped({"sensor.zon"}, False, "<html>Bad gateway</html>")
        self.assertEqual([s["entityId"] for s in payload.states_to_send(STATES, mapped, legacy, PREFIX)], ["sensor.zon"])

    def test_een_foutpagina_voor_het_eerste_antwoord_stuurt_niets(self):
        mapped, legacy = payload.update_mapped(None, False, "<html>Captive portal</html>")
        self.assertEqual(payload.states_to_send(STATES, mapped, legacy, PREFIX), [])


class VersionTests(unittest.TestCase):
    def test_manifest_en_constante_hebben_dezelfde_versie(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        const = (ROOT / "const.py").read_text(encoding="utf-8")
        self.assertIn(f'INTEGRATION_VERSION = "{manifest["version"]}"', const)


# --- de prijsfeed (integratie 1.2.0) --------------------------------------------------------------------------------------------------------------------------------------------------------
# De portal zegt in zijn antwoord welke sensor de prijssensor is (priceEntity); de integratie leest daarvan de attributen raw_today en raw_tomorrow (een lijst van {start, end, value}) en stuurt ze
# in de push mee (priceForecast). Alles hieronder draait zonder Home Assistant: de toestandsobjecten zijn nagemaakt zoals bij STATES.

AMS_WINTER = timezone(timedelta(hours=1))  # +01:00
AMS_SUMMER = timezone(timedelta(hours=2))  # +02:00
PRICE_ENTITY = "sensor.stroomprijs"
MAX_SLOTS = const.PRICE_FEED_MAX_SLOTS  # de grens van de portal: 288 (zie PortalLimitTests)
RESEND = 1800
MIN_INTERVAL = 360


def quarter(start: datetime, value, **extra):
    return {"start": start, "end": start + timedelta(minutes=15), "value": value, **extra}


def day_items(first: datetime, count: int, base=0.2):
    """`count` aaneengesloten kwartier-items vanaf `first` (HA geeft datetime-objecten met verschuiving)."""
    return [quarter(first + timedelta(minutes=15 * i), round(base + i / 1000, 6)) for i in range(count)]


def price_state(raw_today=None, raw_tomorrow=None, entity_id=PRICE_ENTITY, unit="EUR/kWh", value="0.2", **extra):
    attrs = {"friendly_name": "Stroomprijs", **extra}
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    if raw_today is not None:
        attrs["raw_today"] = raw_today
    if raw_tomorrow is not None:
        attrs["raw_tomorrow"] = raw_tomorrow
    return state(entity_id, value, datetime(2026, 11, 13, 14, 7, tzinfo=AMS_WINTER), **attrs)


TODAY = day_items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER), 96)
TOMORROW = day_items(datetime(2026, 11, 14, 0, 0, tzinfo=AMS_WINTER), 96, base=0.3)


def build(state_, **kw):
    return payload.build_price_forecast(state_, kw.get("prefix", PREFIX), kw.get("max_slots", MAX_SLOTS))


class PriceEntityTests(unittest.TestCase):
    def test_de_prijssensor_uit_het_antwoord(self):
        self.assertEqual(payload.parse_price_entity({"ok": True, "mapped": [], "priceEntity": PRICE_ENTITY}), PRICE_ENTITY)

    def test_null_ontbrekend_of_rommel_is_geen_prijssensor(self):
        for response in ({"priceEntity": None}, {"ok": True}, {"priceEntity": ""}, {"priceEntity": 5}, {"priceEntity": ["sensor.a"]}, {"priceEntity": True}):
            self.assertIsNone(payload.parse_price_entity(response), repr(response))
        for response in (None, "tekst", 502, [], ["priceEntity"], "<html>Fout</html>"):
            self.assertIsNone(payload.parse_price_entity(response), repr(response))

    def test_een_leesbaar_antwoord_wint_een_onleesbaar_antwoord_laat_staan_wat_we_wisten(self):
        self.assertEqual(payload.update_price_entity(None, {"priceEntity": PRICE_ENTITY}), PRICE_ENTITY)
        self.assertEqual(payload.update_price_entity("sensor.oud", {"priceEntity": PRICE_ENTITY}), PRICE_ENTITY)
        self.assertIsNone(payload.update_price_entity(PRICE_ENTITY, {"priceEntity": None}), "de portal zegt: geen prijssensor (meer)")
        self.assertIsNone(payload.update_price_entity(PRICE_ENTITY, {"ok": True, "mapped": []}), "een oudere portal kent het veld niet: niets sturen")
        for rommel in (None, "<html>Bad gateway</html>", 502, [], ["priceEntity"]):
            self.assertEqual(payload.update_price_entity(PRICE_ENTITY, rommel), PRICE_ENTITY, repr(rommel))
            self.assertIsNone(payload.update_price_entity(None, rommel), repr(rommel))


class BuildPriceForecastTests(unittest.TestCase):
    def test_vandaag_en_morgen_met_datetime_attributen_als_iso_tekst_met_verschuiving(self):
        forecast = build(price_state(TODAY, TOMORROW))
        self.assertEqual(forecast["entityId"], PRICE_ENTITY)
        self.assertEqual(forecast["unitOfMeasurement"], "EUR/kWh")
        self.assertEqual(forecast["attributes"], "raw_today+raw_tomorrow")
        self.assertEqual(len(forecast["slots"]), 192)
        self.assertEqual(forecast["slots"][0], {"start": "2026-11-13T00:00:00+01:00", "value": 0.2})
        self.assertEqual(forecast["slots"][95], {"start": "2026-11-13T23:45:00+01:00", "value": 0.295})
        self.assertEqual(forecast["slots"][96], {"start": "2026-11-14T00:00:00+01:00", "value": 0.3})
        self.assertEqual(forecast["slots"][191]["start"], "2026-11-14T23:45:00+01:00")
        for slot in forecast["slots"]:
            self.assertEqual(set(slot), {"start", "value"}, "alleen begintijd en prijs: geen eindtijd, geen andere velden")

    def test_attributen_als_tekst_gaan_ook_mee(self):
        today = [{"start": "2026-11-13T00:00:00+01:00", "end": "2026-11-13T00:15:00+01:00", "value": 0.429}, {"start": "2026-11-13T00:15:00+01:00", "end": "x", "value": 1}]
        forecast = build(price_state(today))
        self.assertEqual(forecast["slots"], [{"start": "2026-11-13T00:00:00+01:00", "value": 0.429}, {"start": "2026-11-13T00:15:00+01:00", "value": 1.0}])
        # een tekst die niet precies ISO is maar wel een tijd met verschuiving, wordt genormaliseerd (spatie, Z)
        odd = [{"start": "2026-11-13 00:00:00+01:00", "value": 0.4}, {"start": "2026-11-12T23:15:00Z", "value": 0.5}]
        self.assertEqual([s["start"] for s in build(price_state(odd))["slots"]], ["2026-11-13T00:00:00+01:00", "2026-11-12T23:15:00+00:00"])

    def test_het_naamlabel_noemt_alleen_de_attributen_die_items_gaven(self):
        self.assertEqual(build(price_state(TODAY, []))["attributes"], "raw_today", "voor ongeveer 14:00 is raw_tomorrow nog leeg")
        self.assertEqual(build(price_state(TODAY))["attributes"], "raw_today")
        self.assertEqual(build(price_state(None, TOMORROW))["attributes"], "raw_tomorrow")
        self.assertEqual(build(price_state(TODAY, TOMORROW))["attributes"], "raw_today+raw_tomorrow")
        self.assertNotIn(".", build(price_state(TODAY, TOMORROW))["attributes"], "nooit een entity-id")

    def test_geen_attribuut_geeft_geen_feed(self):
        self.assertIsNone(build(price_state()))
        self.assertIsNone(build(price_state([], [])))
        self.assertIsNone(build(price_state("geen lijst", {"start": 1})))
        self.assertIsNone(build(price_state(None, None, raw_other=TODAY)), "een ander attribuut telt niet")
        self.assertIsNone(build(None), "de sensor bestaat niet")
        self.assertIsNone(build(price_state(TODAY, TOMORROW), prefix="binary_sensor."), "alleen sensor.-entiteiten verlaten Home Assistant")
        self.assertIsNone(build(price_state(TODAY, TOMORROW, entity_id="device_tracker.auto")))

    def test_een_item_zonder_leesbare_start_of_zonder_getal_wordt_overgeslagen(self):
        good = quarter(datetime(2026, 11, 13, 1, 0, tzinfo=AMS_WINTER), 0.5)
        naive = quarter(datetime(2026, 11, 13, 2, 0), 0.5)  # zonder verschuiving: de portal zou de feed weigeren
        bad = [
            {"value": 0.5},
            {"start": None, "value": 0.5},
            {"start": "gisteren", "value": 0.5},
            {"start": 12345, "value": 0.5},
            {"start": "2026-11-13T03:00:00", "value": 0.5},  # tekst zonder verschuiving
            naive,
            quarter(datetime(2026, 11, 13, 4, 0, tzinfo=AMS_WINTER), None),
            quarter(datetime(2026, 11, 13, 4, 15, tzinfo=AMS_WINTER), "0.5"),
            quarter(datetime(2026, 11, 13, 4, 30, tzinfo=AMS_WINTER), True),
            quarter(datetime(2026, 11, 13, 4, 45, tzinfo=AMS_WINTER), float("nan")),
            quarter(datetime(2026, 11, 13, 5, 0, tzinfo=AMS_WINTER), float("inf")),
            quarter(datetime(2026, 11, 13, 5, 15, tzinfo=AMS_WINTER), float("-inf")),
            None,
            5,
            "tekst",
            [],
        ]
        good_after = quarter(datetime(2026, 11, 13, 1, 15, tzinfo=AMS_WINTER), 0.6)
        forecast = build(price_state([good, *bad, good_after]))
        self.assertEqual(forecast["slots"], [{"start": "2026-11-13T01:00:00+01:00", "value": 0.5}, {"start": "2026-11-13T01:15:00+01:00", "value": 0.6}])
        self.assertIsNone(build(price_state([good, *bad])), "een enkel leesbaar item is te weinig: de portal eist minstens twee slots")
        self.assertIsNone(build(price_state(bad)), "geen enkel leesbaar item: geen feed")

    def test_het_resultaat_is_geldige_json_zonder_nan_of_infinity(self):
        forecast = build(price_state([*TODAY, quarter(datetime(2026, 11, 13, 5, 0, tzinfo=AMS_WINTER), float("nan"))], TOMORROW))
        text = json.dumps(forecast, allow_nan=False)  # gooit bij NaN of Infinity: de portal zou de HELE push als ongeldige JSON weigeren
        self.assertEqual(json.loads(text)["slots"][0]["value"], 0.2)

    def test_hooguit_max_slots_items(self):
        many = day_items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER), 300)
        self.assertEqual(len(build(price_state(many, many))["slots"]), MAX_SLOTS)
        self.assertEqual(len(build(price_state(many, many), max_slots=10)["slots"]), 10)
        self.assertEqual(build(price_state(many), max_slots=10)["slots"][-1]["start"], "2026-11-13T02:15:00+01:00", "de eerste items, in de volgorde van de sensor")
        self.assertEqual(len(build(price_state(day_items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER), MAX_SLOTS)))["slots"]), MAX_SLOTS, "precies op de grens: alles")

    def test_de_eenheid_gaat_mee_en_onbekend_is_null(self):
        self.assertEqual(build(price_state(TODAY, unit="ct/kWh"))["unitOfMeasurement"], "ct/kWh")
        self.assertIsNone(build(price_state(TODAY, unit=None))["unitOfMeasurement"])
        self.assertIsNone(build(price_state(TODAY, unit="x" * 65)), "een eenheid van meer dan 64 tekens: de portal zou de hele push weigeren, dus geen feed")
        self.assertEqual(build(price_state(TODAY, unit="x" * 64))["unitOfMeasurement"], "x" * 64)
        self.assertIsNone(build(price_state(TODAY, unit=5)))
        self.assertIsNone(build(price_state(TODAY, entity_id="sensor." + "x" * 250)), "een entity-id van meer dan 255 tekens bestaat niet, maar zou de hele push laten weigeren")

    def test_de_dag_van_de_omschakeling_over_de_verschuiving_heen(self):
        """25 oktober 2026: 100 kwartieren, de verschuiving gaat van +02:00 naar +01:00 midden in de lijst; elke begintijd is uniek, ook die van de dubbele wandtijd 02:00 tot 03:00."""
        start = datetime(2026, 10, 25, 0, 0, tzinfo=AMS_SUMMER)
        items = []
        for i in range(100):
            moment = start + timedelta(minutes=15 * i)  # absolute tijd; de verschuiving van de tweede helft is +01:00
            local = moment.astimezone(AMS_SUMMER if i < 12 else AMS_WINTER)  # 02:00 +02:00 is kwartier 8; om 03:00 +02:00 (= 02:00 +01:00) gaat de klok terug
            items.append(quarter(local, 0.2 + i / 1000))
        slots = build(price_state(items))["slots"]
        self.assertEqual(len(slots), 100)
        self.assertEqual(slots[0]["start"], "2026-10-25T00:00:00+02:00")
        self.assertEqual(slots[11]["start"], "2026-10-25T02:45:00+02:00")
        self.assertEqual(slots[12]["start"], "2026-10-25T02:00:00+01:00", "dezelfde wandtijd als kwartier 8, met de andere verschuiving")
        self.assertEqual(slots[99]["start"], "2026-10-25T23:45:00+01:00")
        self.assertEqual(len({s["start"] for s in slots}), 100)
        # en de lente: 92 kwartieren, de verschuiving gaat van +01:00 naar +02:00
        spring = datetime(2027, 3, 28, 0, 0, tzinfo=AMS_WINTER)
        items = []
        for i in range(92):
            moment = spring + timedelta(minutes=15 * i)
            items.append(quarter(moment.astimezone(AMS_WINTER if i < 8 else AMS_SUMMER), 0.2))
        slots = build(price_state(items))["slots"]
        self.assertEqual((slots[7]["start"], slots[8]["start"]), ("2027-03-28T01:45:00+01:00", "2027-03-28T03:00:00+02:00"))
        self.assertEqual(len(slots), 92)


class SignatureTests(unittest.TestCase):
    def forecast(self, **kw):
        return build(price_state(kw.get("today", TODAY), kw.get("tomorrow", TOMORROW), unit=kw.get("unit", "EUR/kWh")))

    def test_dezelfde_inhoud_geeft_dezelfde_handtekening_ook_uit_nieuwe_objecten(self):
        a = payload.price_forecast_signature(self.forecast())
        b = payload.price_forecast_signature(self.forecast(today=day_items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER), 96)))
        self.assertIsInstance(a, str)
        self.assertEqual(a, b)
        self.assertEqual(a, payload.price_forecast_signature(self.forecast()))

    def test_een_andere_waarde_begintijd_eenheid_of_aantal_geeft_een_andere_handtekening(self):
        base = payload.price_forecast_signature(self.forecast())
        changed_value = [dict(i) for i in TODAY]
        changed_value[50]["value"] = 0.9
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(today=changed_value)))
        tiny = [dict(i) for i in TODAY]
        tiny[50]["value"] = tiny[50]["value"] + 0.000001
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(today=tiny)), "ook een verschil in de zesde decimaal")
        shifted = day_items(datetime(2026, 11, 13, 0, 15, tzinfo=AMS_WINTER), 96)
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(today=shifted)))
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(unit="ct/kWh")))
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(tomorrow=[])), "de prijzen van morgen verdwijnen (middernacht) of komen (14:00)")
        self.assertNotEqual(base, payload.price_forecast_signature(self.forecast(today=TODAY[:-1])))

    def test_geen_feed_geen_handtekening(self):
        self.assertIsNone(payload.price_forecast_signature(None))

    def test_een_andere_sensor_geeft_een_andere_handtekening(self):
        other = build(price_state(TODAY, TOMORROW, entity_id="sensor.andere_prijs"))
        self.assertNotEqual(payload.price_forecast_signature(self.forecast()), payload.price_forecast_signature(other))


class ShouldSendPriceForecastTests(unittest.TestCase):
    def should(self, signature, last_signature, last_sent_at, now):
        return payload.should_send_price_forecast(signature, last_signature, last_sent_at, now, RESEND, MIN_INTERVAL)

    def test_de_eerste_keer(self):
        self.assertTrue(self.should("a", None, None, 1000.0))

    def test_een_verandering_gaat_mee_maar_niet_vaker_dan_eens_per_6_minuten(self):
        self.assertFalse(self.should("b", "a", 1000.0, 1001.0), "een sensor die bij elke tick verandert stuurt niet elke tick")
        self.assertFalse(self.should("b", "a", 1000.0, 1000.0 + MIN_INTERVAL - 0.001))
        self.assertTrue(self.should("b", "a", 1000.0, 1000.0 + MIN_INTERVAL), "precies na 6 minuten")
        self.assertTrue(self.should("b", "a", 1000.0, 1000.0 + MIN_INTERVAL + 1))
        self.assertEqual(MIN_INTERVAL, 360)
        self.assertLessEqual(3600 / MIN_INTERVAL, 10, "hooguit 10 verzendingen per uur: een marge van 2 onder de 12 per uur die de portal verwerkt")

    def test_dezelfde_inhoud_alleen_na_de_herhaaltijd(self):
        self.assertFalse(self.should("a", "a", 1000.0, 1000.0), "dezelfde push")
        self.assertFalse(self.should("a", "a", 1000.0, 1030.0), "30 seconden later (de volgende push)")
        self.assertFalse(self.should("a", "a", 1000.0, 1000.0 + MIN_INTERVAL), "6 minuten is voor een verandering, niet voor een herhaling")
        self.assertFalse(self.should("a", "a", 1000.0, 1000.0 + RESEND - 0.001))
        self.assertTrue(self.should("a", "a", 1000.0, 1000.0 + RESEND), "precies na 30 minuten")
        self.assertTrue(self.should("a", "a", 1000.0, 1000.0 + RESEND + 60))

    def test_zonder_feed_nooit(self):
        for last, sent in ((None, None), ("a", 1000.0)):
            self.assertFalse(self.should(None, last, sent, 99999.0))

    def test_een_handtekening_zonder_tijd_van_versturen_geldt_als_nog_niet_verstuurd(self):
        self.assertTrue(self.should("a", "a", None, 1000.0))
        self.assertTrue(self.should("b", "a", None, 1000.0))


class ScanCeilingTests(unittest.TestCase):
    """Een attribuut met miljoenen items of vol rommel houdt de push niet op: hooguit PRICE_FEED_SCAN_FACTOR keer max_slots items worden bekeken, de overgeslagen items tellen mee."""

    class Teller(list):
        def __init__(self, *args):
            super().__init__(*args)
            self.gezien = 0

        def __getitem__(self, key):
            # de integratie neemt een plak van de lijst (hooguit het plafond): zo is te tellen hoeveel items er worden aangeraakt
            result = super().__getitem__(key)
            if isinstance(key, slice):
                self.gezien += len(result)
            return result

    def test_de_factor_is_2(self):
        self.assertEqual(payload.PRICE_FEED_SCAN_FACTOR, 2)

    def test_een_lijst_vol_rommel_wordt_niet_helemaal_bekeken(self):
        rommel = self.Teller([None] * 1_000_000)
        self.assertIsNone(build(price_state(rommel, rommel)))
        self.assertLessEqual(rommel.gezien, MAX_SLOTS * payload.PRICE_FEED_SCAN_FACTOR, "hooguit het plafond aan bekeken items, over beide attributen samen")

    def test_het_plafond_telt_overgeslagen_items_mee_en_loopt_over_beide_attributen(self):
        good = day_items(datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER), 5)
        junk = [None] * 3
        forecast = build(price_state([*junk, *good], [*junk, *good]), max_slots=10)  # plafond: 20 bekeken items, hier 16 nodig
        self.assertEqual(len(forecast["slots"]), 10, "de goede items na de rommel zijn gevonden")
        # met 15 stuks rommel voor de goede items is het plafond (20) voor het einde van het eerste attribuut: 5 goede items, en het tweede attribuut wordt niet meer bekeken
        junk15 = [None] * 15
        forecast = build(price_state([*junk15, *good, *good], [*good]), max_slots=10)
        self.assertEqual(len(forecast["slots"]), 5)
        self.assertEqual(forecast["attributes"], "raw_today")
        # zonder dat de goede items het plafond halen blijven ze allemaal
        self.assertEqual(len(build(price_state(TODAY, TOMORROW))["slots"]), 192)

    def test_een_gewone_lijst_van_192_wordt_helemaal_bekeken(self):
        teller = self.Teller(TODAY)
        teller2 = self.Teller(TOMORROW)
        self.assertEqual(len(build(price_state(teller, teller2))["slots"]), 192)
        self.assertEqual((teller.gezien, teller2.gezien), (96, 96))


class RetryDelayTests(unittest.TestCase):
    def test_de_wachttijd_verdubbelt_tot_het_maximum(self):
        delays = [payload.price_retry_delay(n, 60, 1800) for n in range(1, 9)]
        self.assertEqual(delays, [60, 120, 240, 480, 960, 1800, 1800, 1800])

    def test_de_eerste_poging_wacht_de_basistijd_en_vreemde_aantallen_geven_geen_fout(self):
        self.assertEqual(payload.price_retry_delay(1, 60, 1800), 60)
        self.assertEqual(payload.price_retry_delay(0, 60, 1800), 60)
        self.assertEqual(payload.price_retry_delay(-5, 60, 1800), 60)
        self.assertEqual(payload.price_retry_delay(10_000, 60, 1800), 1800, "geen overflow bij een heel groot aantal mislukkingen")


class PriceForecastToSendTests(unittest.TestCase):
    def send(self, price_state_, entity=PRICE_ENTITY, last_signature=None, last_sent=None, now=5000.0, on_error=None, retry_not_before=None):
        return payload.price_forecast_to_send(lambda _entity: price_state_, entity, PREFIX, MAX_SLOTS, last_signature, last_sent, now, RESEND, MIN_INTERVAL, retry_not_before, on_error)

    def test_een_portal_zonder_priceEntity_krijgt_niets_dus_de_push_is_gelijk_aan_die_van_1_1_0(self):
        self.assertEqual(self.send(price_state(TODAY, TOMORROW), entity=None), (None, None))
        self.assertEqual(self.send(price_state(TODAY, TOMORROW), entity=""), (None, None))
        # de standen van die push zijn daarbij precies die van 1.1.0
        mapped = {"sensor.zon"}
        self.assertEqual([s["entityId"] for s in payload.states_to_send(STATES, mapped, False, PREFIX)], ["sensor.zon"])

    def test_zonder_priceEntity_wordt_de_toestand_niet_eens_gelezen(self):
        def boom(_entity):
            raise AssertionError("de toestand van de prijssensor mag niet gelezen worden zonder priceEntity")

        self.assertEqual(payload.price_forecast_to_send(boom, None, PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL), (None, None))

    def test_met_priceEntity_de_feed_en_zijn_handtekening_de_eerste_keer(self):
        forecast, signature = self.send(price_state(TODAY, TOMORROW))
        self.assertEqual(len(forecast["slots"]), 192)
        self.assertEqual(signature, payload.price_forecast_signature(forecast))

    def test_de_toestand_wordt_opgevraagd_van_de_sensor_die_de_portal_noemt(self):
        asked = []

        def get_state(entity):
            asked.append(entity)
            return price_state(TODAY, TOMORROW)

        payload.price_forecast_to_send(get_state, PRICE_ENTITY, PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL)
        self.assertEqual(asked, [PRICE_ENTITY])

    def test_daarna_niet_meer_tot_er_na_6_minuten_iets_verandert_of_de_herhaaltijd_om_is(self):
        forecast, signature = self.send(price_state(TODAY, TOMORROW))
        self.assertEqual(self.send(price_state(TODAY, TOMORROW), last_signature=signature, last_sent=5000.0, now=5030.0), (None, None))
        changed = [dict(i) for i in TODAY]
        changed[3]["value"] = 0.77
        self.assertEqual(self.send(price_state(changed, TOMORROW), last_signature=signature, last_sent=5000.0, now=5030.0), (None, None), "een verandering binnen 6 minuten wacht")
        again, new_signature = self.send(price_state(changed, TOMORROW), last_signature=signature, last_sent=5000.0, now=5000.0 + MIN_INTERVAL)
        self.assertIsNotNone(again)
        self.assertNotEqual(new_signature, signature)
        self.assertIsNotNone(self.send(price_state(TODAY, TOMORROW), last_signature=signature, last_sent=5000.0, now=5000.0 + RESEND)[0])

    def test_een_sensor_zonder_de_attributen_geeft_niets_en_de_andere_standen_blijven_ongemoeid(self):
        self.assertEqual(self.send(price_state()), (None, None))
        self.assertEqual(self.send(None), (None, None))

    def test_na_een_lijst_die_niet_aankwam_gaat_er_niets_voor_retry_not_before_ook_geen_veranderde_lijst(self):
        forecast, signature = self.send(price_state(TODAY, TOMORROW))
        changed = [dict(i) for i in TODAY]
        changed[3]["value"] = 0.77
        # nog niet verstuurd (de eerste keer) maar een eerdere poging mislukte: wachten tot het moment
        self.assertEqual(self.send(price_state(TODAY, TOMORROW), now=5059.0, retry_not_before=5060.0), (None, None))
        self.assertEqual(self.send(price_state(changed, TOMORROW), last_signature=signature, last_sent=1.0, now=9999.0, retry_not_before=10000.0), (None, None), "ook een veranderde lijst wacht")
        again, _ = self.send(price_state(TODAY, TOMORROW), now=5060.0, retry_not_before=5060.0)
        self.assertIsNotNone(again, "precies op het moment mag het weer")
        self.assertIsNotNone(self.send(price_state(TODAY, TOMORROW), now=5061.0, retry_not_before=5060.0)[0])
        self.assertIsNotNone(self.send(price_state(TODAY, TOMORROW), now=5000.0, retry_not_before=None)[0], "zonder wachttijd gewoon de eerste keer")

    def test_een_fout_in_het_prijsdeel_geeft_geen_prijslijst_en_gooit_nooit(self):
        """De prijslijst mag de gewone push nooit stoppen: wat er ook misgaat (de toestand lezen, een vreemd attribuut, een eigen fout) is een push zonder prijslijst."""

        class Kapot:
            entity_id = PRICE_ENTITY

            @property
            def attributes(self):
                raise RuntimeError("kapot attribuut")

        class KapotItem:
            def get(self, _key, _default=None):
                raise ValueError("kapot item")

        def get_state_raises(_entity):
            raise KeyError("geen toestand")

        errors = []
        self.assertEqual(self.send(Kapot(), on_error=errors.append), (None, None))
        self.assertEqual(self.send(price_state([KapotItem()]), on_error=errors.append), (None, None))
        self.assertEqual(payload.price_forecast_to_send(get_state_raises, PRICE_ENTITY, PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL, None, errors.append), (None, None))
        self.assertEqual([type(e).__name__ for e in errors], ["RuntimeError", "ValueError", "KeyError"], "de fouten worden gemeld")
        # ook zonder melder, en met een melder die zelf stukgaat
        self.assertEqual(self.send(Kapot()), (None, None))

        def kapotte_melder(_err):
            raise RuntimeError("de melder is stuk")

        self.assertEqual(self.send(Kapot(), on_error=kapotte_melder), (None, None))

    def test_een_getal_dat_niet_in_een_float_past_stopt_niets(self):
        """Een geheel getal boven 1e308 geeft OverflowError bij float(): dat item telt als geen getal, de rest van de lijst gaat gewoon mee."""
        huge = 10**400
        with self.assertRaises(OverflowError):
            float(huge)  # het uitgangspunt van deze toets
        self.assertIsNone(payload._price_value(huge))
        self.assertIsNone(payload._price_value(-huge))
        self.assertEqual(payload._price_value(10**300), 1e300)
        items = [*TODAY[:3], quarter(datetime(2026, 11, 13, 1, 0, tzinfo=AMS_WINTER), huge), quarter(datetime(2026, 11, 13, 1, 15, tzinfo=AMS_WINTER), -huge)]
        forecast, _ = self.send(price_state(items))
        self.assertEqual(len(forecast["slots"]), 3)
        self.assertEqual(self.send(price_state([quarter(datetime(2026, 11, 13, 1, 0, tzinfo=AMS_WINTER), huge)])), (None, None), "alleen onbruikbare items: geen lijst, geen fout")
        json.dumps(forecast, allow_nan=False)

    def test_een_vreemd_getaltype_stopt_niets(self):
        class RaaktIntEnFloat(int):
            def __float__(self):
                raise ArithmeticError("geen float")

        self.assertIsNone(payload._price_value(RaaktIntEnFloat(5)))
        self.assertIsNone(payload._price_value(None))
        self.assertEqual(payload._price_value(0), 0.0)
        self.assertEqual(payload._price_value(-0.05), -0.05)


# --- het formaat van de Zonneplan-integratie: het attribuut forecast ------------------------------------------------------------------------------------------------------------------------
# De sensor "Huidig kwartier elektriciteitstarief": de stand is de prijs van het lopende kwartier (0,4085419 euro per kWh, eenheid "€/kWh"), het attribuut forecast een lijst van aaneengesloten kwartier-items
# van gisteren 07:00 tot het einde van vandaag (164 items op 14 november 2026, 07:56). amount is een geheel getal in 1e-7 euro per kWh en gelijk aan de stand: price_tax_included.

ZP_ENTITY = "sensor.zonneplan_current_quarter_hourly_electricity_tariff"
ZP_FIRST = datetime(2026, 11, 13, 7, 0, tzinfo=AMS_WINTER)  # gisteren 07:00
ZP_COUNT = 164
ZP_LITERAL_INDEX = 99  # 24 uur en 45 minuten na ZP_FIRST: 14 november 07:45, het lopende kwartier om 07:56
ZP_STATE = "0.4085419"
ZP_EXCLUDED = 1_234_567  # een bedrag zonder belasting: dat mag nergens in een uitkomst terugkomen
ZP_LITERAL = {
    "start_date": "2026-11-14T07:45:00+01:00",
    "end_date": "2026-11-14T08:00:00+01:00",
    "price_tax_included": {"amount": 4085419},
    "price_tax_excluded": {"amount": 2976938},
    "sustainability_score": {"permille": 169},
}
MISSING = object()


def zp_item(start: datetime, included, excluded=ZP_EXCLUDED, text=True):
    end = start + timedelta(minutes=15)
    return {
        "start_date": start.isoformat() if text else start,
        "end_date": end.isoformat() if text else end,
        "price_tax_included": {"amount": included},
        "price_tax_excluded": {"amount": excluded},
        "sustainability_score": {"permille": 169},
    }


def zp_list(count=ZP_COUNT, first=ZP_FIRST, text=True):
    """`count` aaneengesloten kwartier-items vanaf `first`; het item van 14 november 07:45 is de letterlijke vorm uit Home Assistant."""
    items = [zp_item(first + timedelta(minutes=15 * i), 3_000_000 + 1000 * i, text=text) for i in range(count)]
    if first == ZP_FIRST and count > ZP_LITERAL_INDEX:
        items[ZP_LITERAL_INDEX] = zp_item(first + timedelta(minutes=15 * ZP_LITERAL_INDEX), 4085419, 2976938, text=text)
    return items


def zp_pair(start: datetime, included, excluded=ZP_EXCLUDED):
    """Twee aaneengesloten kwartieren, het eerste met `included`: een lijst met minder dan twee slots weigert de portal altijd, dus een toets op de waarde van een enkel item heeft er twee nodig."""
    return [zp_item(start, included, excluded), zp_item(start + timedelta(minutes=15), 3_000_000)]


def zp_state(forecast, unit="€/kWh", value=ZP_STATE, entity_id=ZP_ENTITY, **extra):
    attrs = {"friendly_name": "Huidig kwartier elektriciteitstarief", **extra}
    if forecast is not MISSING:
        attrs["forecast"] = forecast
    if unit is not None:
        attrs["unit_of_measurement"] = unit
    return state(entity_id, value, datetime(2026, 11, 14, 7, 56, tzinfo=AMS_WINTER), **attrs)


def zp_with(item, **changes):
    out = dict(item)
    for key, value in changes.items():
        if value is MISSING:
            out.pop(key, None)
        else:
            out[key] = value
    return out


# Elk van deze maakt van een item een item dat de integratie niet kan lezen: het item wordt overgeslagen.
UNREADABLE_ITEMS = [
    ("geen price_tax_included", lambda i: zp_with(i, price_tax_included=MISSING)),
    ("price_tax_included is None", lambda i: zp_with(i, price_tax_included=None)),
    ("price_tax_included is een getal", lambda i: zp_with(i, price_tax_included=4085419)),
    ("price_tax_included is een tekst", lambda i: zp_with(i, price_tax_included="4085419")),
    ("price_tax_included is een lijst", lambda i: zp_with(i, price_tax_included=[4085419])),
    ("alleen price_tax_excluded", lambda i: zp_with(i, price_tax_included=MISSING, price_tax_excluded={"amount": 2976938})),
    ("geen amount", lambda i: zp_with(i, price_tax_included={})),
    ("amount None", lambda i: zp_with(i, price_tax_included={"amount": None})),
    ("amount tekst", lambda i: zp_with(i, price_tax_included={"amount": "4085419"})),
    ("amount True", lambda i: zp_with(i, price_tax_included={"amount": True})),
    ("amount False", lambda i: zp_with(i, price_tax_included={"amount": False})),
    ("amount met breuk", lambda i: zp_with(i, price_tax_included={"amount": 4085419.5})),
    ("amount NaN", lambda i: zp_with(i, price_tax_included={"amount": float("nan")})),
    ("amount oneindig", lambda i: zp_with(i, price_tax_included={"amount": float("inf")})),
    ("amount min oneindig", lambda i: zp_with(i, price_tax_included={"amount": float("-inf")})),
    ("amount lijst", lambda i: zp_with(i, price_tax_included={"amount": [4085419]})),
    ("amount dict", lambda i: zp_with(i, price_tax_included={"amount": {}})),
    ("amount boven het bereik van de portal", lambda i: zp_with(i, price_tax_included={"amount": 50_000_001})),
    ("amount onder het bereik van de portal", lambda i: zp_with(i, price_tax_included={"amount": -10_000_001})),
    ("amount 10**400", lambda i: zp_with(i, price_tax_included={"amount": 10**400})),
    ("amount -10**400", lambda i: zp_with(i, price_tax_included={"amount": -(10**400)})),
    ("geen start_date", lambda i: zp_with(i, start_date=MISSING)),
    ("start_date None", lambda i: zp_with(i, start_date=None)),
    ("start_date is onleesbare tekst", lambda i: zp_with(i, start_date="gisteren")),
    ("start_date is een getal", lambda i: zp_with(i, start_date=12345)),
    ("start_date zonder verschuiving (tekst)", lambda i: zp_with(i, start_date="2026-11-13T09:00:00")),
    ("start_date zonder verschuiving (datetime)", lambda i: zp_with(i, start_date=datetime(2026, 11, 13, 9, 0))),
    ("geen end_date", lambda i: zp_with(i, end_date=MISSING)),
    ("end_date None", lambda i: zp_with(i, end_date=None)),
    ("end_date zonder verschuiving", lambda i: zp_with(i, end_date="2026-11-13T09:15:00")),
]


class ZonneplanFormatTests(unittest.TestCase):
    def test_de_testgegevens_zijn_de_letterlijke_vorm_uit_home_assistant(self):
        self.assertEqual(zp_item(datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER), 4085419, 2976938), ZP_LITERAL)
        self.assertEqual(zp_list()[ZP_LITERAL_INDEX], ZP_LITERAL)
        self.assertEqual(len(zp_list()), 164)
        self.assertEqual(zp_list()[0]["start_date"], "2026-11-13T07:00:00+01:00")
        self.assertEqual(zp_list()[-1]["end_date"], "2026-11-15T00:00:00+01:00")

    def test_het_letterlijke_item_geeft_begintijd_en_prijs_in_euro_per_kwh(self):
        following = zp_item(datetime(2026, 11, 14, 8, 0, tzinfo=AMS_WINTER), 4_100_000)  # het kwartier erna: de portal eist minstens twee slots
        forecast = build(zp_state([ZP_LITERAL, following]))
        self.assertEqual(
            forecast,
            {
                "entityId": ZP_ENTITY,
                "unitOfMeasurement": "EUR/kWh",
                "attributes": "forecast",
                "slots": [{"start": "2026-11-14T07:45:00+01:00", "value": 0.4085419}, {"start": "2026-11-14T08:00:00+01:00", "value": 0.41}],
            },
        )

    def test_de_volledige_structuur_van_164_items_met_de_stand_gelijk_aan_het_lopende_kwartier(self):
        forecast = build(zp_state(zp_list()))
        slots = forecast["slots"]
        self.assertEqual(forecast["entityId"], ZP_ENTITY)
        self.assertEqual(forecast["unitOfMeasurement"], "EUR/kWh", "de sensor zegt €/kWh, de portal krijgt EUR/kWh")
        self.assertEqual(forecast["attributes"], "forecast")
        self.assertEqual(len(slots), 164)
        self.assertEqual(slots[0], {"start": "2026-11-13T07:00:00+01:00", "value": 0.3})
        self.assertEqual(slots[-1]["start"], "2026-11-14T23:45:00+01:00")
        for i, slot in enumerate(slots):
            self.assertEqual(set(slot), {"start", "value"}, "alleen begintijd en prijs")
            if i != ZP_LITERAL_INDEX:
                self.assertEqual(slot["value"], (3_000_000 + 1000 * i) / 1e7)
        # aaneengesloten, elk precies een kwartier, en elke begintijd op een kwartiergrens (zoals de portal het vraagt)
        starts = [datetime.fromisoformat(s["start"]) for s in slots]
        for before, after in zip(starts, starts[1:]):
            self.assertEqual(after - before, timedelta(minutes=15))
        for start in starts:
            self.assertEqual(start.timestamp() % 900, 0)
        # de stand van de sensor is het bedrag van het lopende kwartier (14 november 07:56: het kwartier van 07:45)
        now = datetime(2026, 11, 14, 7, 56, tzinfo=AMS_WINTER)
        current = [s for s, start in zip(slots, starts) if start <= now < start + timedelta(minutes=15)]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0], {"start": "2026-11-14T07:45:00+01:00", "value": 0.4085419})
        self.assertEqual(current[0]["value"], float(ZP_STATE))
        # alleen price_tax_included: de bedragen zonder belasting (1234567 en 2976938) en de rest van het item verlaten Home Assistant niet
        text = json.dumps(forecast, allow_nan=False)
        for niet in ("2976938", "0.2976938", "1234567", "0.1234567", "price_tax", "sustainability", "end_date", "permille"):
            self.assertNotIn(niet, text)
        for slot in slots:
            self.assertTrue(-1 <= slot["value"] <= 5)

    def test_datetime_objecten_geven_hetzelfde_als_tekst(self):
        self.assertEqual(build(zp_state(zp_list(text=False))), build(zp_state(zp_list(text=True))))
        mixed = [zp_with(item, start_date=datetime.fromisoformat(item["start_date"])) if i % 2 else item for i, item in enumerate(zp_list())]
        self.assertEqual(build(zp_state(mixed)), build(zp_state(zp_list())))
        self.assertEqual(build(zp_state(tuple(zp_list()))), build(zp_state(zp_list())), "ook een tuple is een lijst")

    def test_tekst_wordt_genormaliseerd_en_tekst_zonder_verschuiving_is_onleesbaar(self):
        z = [
            {**zp_item(datetime(2026, 11, 14, 6, 45, tzinfo=timezone.utc), 4_000_000), "start_date": "2026-11-14T06:45:00Z", "end_date": "2026-11-14T07:00:00Z"},
            {**zp_item(datetime(2026, 11, 14, 7, 0, tzinfo=timezone.utc), 4_000_001), "start_date": "2026-11-14 07:00:00+00:00", "end_date": " 2026-11-14T07:15:00+00:00 "},
        ]
        self.assertEqual([s["start"] for s in build(zp_state(z))["slots"]], ["2026-11-14T06:45:00+00:00", "2026-11-14T07:00:00+00:00"])
        naive = zp_list(count=4, text=True)
        for item in naive:
            item["start_date"] = item["start_date"][:19]  # zonder verschuiving
        self.assertIsNone(build(zp_state(naive)), "de portal kent de tijdzone niet: onleesbaar, dus niets")

    def test_de_schaal_is_1e_7_euro_per_kwh(self):
        start = datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER)
        for amount, euro in ((4085419, 0.4085419), (10_000_000, 1.0), (1, 1e-07), (0, 0.0), (-123456, -0.0123456), (5_000_000, 0.5), (50_000_000, 5.0), (-10_000_000, -1.0), (2, 2e-07)):
            slots = build(zp_state(zp_pair(start, amount)))["slots"]
            self.assertEqual(slots, [{"start": "2026-11-14T07:45:00+01:00", "value": euro}, {"start": "2026-11-14T08:00:00+01:00", "value": 0.3}], amount)
            self.assertEqual(slots[0]["value"], amount / 1e7)

    def test_een_geheel_getal_als_float_is_ook_een_geheel_getal_maar_met_breuk_niet(self):
        start = datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER)
        self.assertEqual(build(zp_state(zp_pair(start, 4085419.0)))["slots"][0]["value"], 0.4085419)
        # het eerste item is onleesbaar en wordt overgeslagen: er blijft een slot over, en met een slot geeft de portal geen lijst
        self.assertIsNone(build(zp_state(zp_pair(start, 4085419.5))))
        self.assertIsNone(build(zp_state(zp_pair(start, 4085419.000001))))

    def test_alleen_price_tax_included_nooit_price_tax_excluded(self):
        start = datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER)
        only_excluded = zp_with(zp_item(start, 4085419, 2976938), price_tax_included=MISSING)
        self.assertIsNone(build(zp_state([only_excluded])), "zonder price_tax_included niets, ook al is er een bedrag zonder belasting")
        both = zp_pair(start, 4085419, 2976938)
        self.assertIsNone(build(zp_state([only_excluded, both[1]])), "het item met alleen price_tax_excluded telt niet mee: er blijft een slot over")
        slots = build(zp_state(both))["slots"]
        self.assertEqual(slots[0]["value"], 0.4085419)
        self.assertNotEqual(slots[0]["value"], 0.2976938)

    def test_een_vreemd_getaltype_stopt_niets(self):
        class RaaktVergelijken(int):
            def __ge__(self, other):
                raise ArithmeticError("geen vergelijking")

            def __le__(self, other):
                raise ArithmeticError("geen vergelijking")

        for vreemd in (RaaktVergelijken(5), RaaktVergelijken(-5)):
            self.assertIsNone(payload._price_amount(vreemd))
        self.assertEqual(payload._price_amount(0), 0.0)
        self.assertEqual(payload._price_amount(-1), -1e-07)
        self.assertIsNone(payload._price_amount(None))

    # --- de eenheid ---

    def test_de_eenheid_met_het_eurosymbool_wordt_eur_kwh_bij_beide_formaten(self):
        self.assertEqual(build(zp_state(zp_list(), unit="€/kWh"))["unitOfMeasurement"], "EUR/kWh")
        self.assertEqual(build(zp_state(zp_list(), unit="EUR/kWh"))["unitOfMeasurement"], "EUR/kWh")
        self.assertEqual(build(price_state(TODAY, TOMORROW, unit="€/kWh"))["unitOfMeasurement"], "EUR/kWh", "ook de raw_today-sensor")
        self.assertEqual(build(price_state(TODAY, TOMORROW, unit="EUR/kWh"))["unitOfMeasurement"], "EUR/kWh")

    def test_alleen_die_ene_eenheid_wordt_omgezet(self):
        for unit in ("ct/kWh", "€/MWh", "EUR/MWh", "euro/kWh", "eur/kwh", "€ /kWh", "x" * 64, "kWh"):
            self.assertEqual(build(price_state(TODAY, unit=unit))["unitOfMeasurement"], unit, f"raw_today: {unit!r} blijft zoals het is")
        self.assertIsNone(build(price_state(TODAY, unit=None))["unitOfMeasurement"], "geen eenheid blijft geen eenheid")

    def test_bij_de_zonneplan_lijst_is_een_andere_eenheid_dan_euro_per_kwh_geen_prijslijst(self):
        """De bedragen zijn altijd euro per kWh: een sensor die iets anders als eenheid noemt (centen, per MWh, kubieke meters) levert geen lijst die de portal goed kan lezen."""
        for unit in ("ct/kWh", "€/MWh", "EUR/MWh", "€/m³", "euro/kWh", "eur/kwh", "kWh", "", "x" * 65, 5, ["€/kWh"]):
            self.assertIsNone(build(zp_state(zp_list(), unit=unit)), repr(unit))

    def test_zonder_eenheid_gaat_de_zonneplan_lijst_mee_als_euro_per_kwh(self):
        forecast = build(zp_state(zp_list(), unit=None))
        self.assertEqual(forecast["unitOfMeasurement"], "EUR/kWh")
        self.assertEqual(len(forecast["slots"]), 164)

    # --- de gasvorm: een lijst die niet uit kwartieren bestaat ---

    def test_de_gassensor_met_een_item_van_24_uur_wordt_nooit_een_kwartierlijst(self):
        gas = [{"start_date": "2026-11-14T06:00:00+01:00", "end_date": "2026-11-15T06:00:00+01:00", "price_tax_included": {"amount": 1_234_567}, "price_tax_excluded": {"amount": 1_000_000}}]
        for unit in ("€/kWh", "EUR/kWh", None, "€/m³"):
            self.assertIsNone(build(zp_state(gas, unit=unit, entity_id="sensor.zonneplan_current_tariff_gas")), repr(unit))
        # ook met datetime-objecten
        gas_dt = [{**gas[0], "start_date": datetime(2026, 11, 14, 6, 0, tzinfo=AMS_WINTER), "end_date": datetime(2026, 11, 15, 6, 0, tzinfo=AMS_WINTER)}]
        self.assertIsNone(build(zp_state(gas_dt)))

    def test_een_lijst_waarin_een_item_geen_kwartier_duurt_gaat_helemaal_niet_mee(self):
        start = datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER)
        for minutes in (0, -15, 1, 14, 16, 30, 60, 1440):
            items = zp_list(count=8)
            items[4] = zp_with(items[4], end_date=(datetime.fromisoformat(items[4]["start_date"]) + timedelta(minutes=minutes)).isoformat())
            self.assertIsNone(build(zp_state(items)), f"een item van {minutes} minuten")
        # ook als het item aan de rand staat, en ook als het item verder niet te lezen is (geen bedrag)
        items = zp_list(count=8)
        items[0] = zp_with(items[0], end_date="2026-11-13T08:00:00+01:00", price_tax_included=MISSING)
        self.assertIsNone(build(zp_state(items)))
        items = zp_list(count=8)
        items[7] = zp_with(items[7], end_date="2026-11-13T10:30:00+01:00")
        self.assertIsNone(build(zp_state(items)))
        # een uurreeks is geen kwartierlijst
        hourly = [zp_with(zp_item(start + timedelta(hours=i), 4_000_000 + i), end_date=(start + timedelta(hours=i + 1)).isoformat()) for i in range(24)]
        self.assertIsNone(build(zp_state(hourly)))
        # twee kwartieren zijn wel een kwartierlijst; een enkel kwartier niet (de portal eist minstens twee slots)
        self.assertEqual(len(build(zp_state(zp_pair(start, 4_000_000)))["slots"]), 2)
        self.assertIsNone(build(zp_state([zp_item(start, 4_000_000)])))

    def test_een_gas_lijst_via_de_hele_keten_gaat_niet_naar_de_portal(self):
        gas = [{"start_date": "2026-11-14T06:00:00+01:00", "end_date": "2026-11-15T06:00:00+01:00", "price_tax_included": {"amount": 1_234_567}}]
        result = payload.price_forecast_to_send(lambda _e: zp_state(gas), "sensor.zonneplan_current_tariff_gas", PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL)
        self.assertEqual(result, (None, None))

    # --- gaten, overlap en volgorde ---

    def test_een_gat_een_dubbel_item_of_een_andere_volgorde_geeft_geen_lijst(self):
        base = zp_list(count=10)
        gap = base[:5] + base[6:]
        self.assertIsNone(build(zp_state(gap)), "een kwartier ontbreekt")
        gap_hours = base[:3] + base[7:]
        self.assertIsNone(build(zp_state(gap_hours)))
        duplicate = base[:5] + [base[4]] + base[5:]
        self.assertIsNone(build(zp_state(duplicate)), "hetzelfde kwartier twee keer")
        swapped = list(base)
        swapped[3], swapped[4] = swapped[4], swapped[3]
        self.assertIsNone(build(zp_state(swapped)), "niet oplopend")
        reversed_items = list(reversed(base))
        self.assertIsNone(build(zp_state(reversed_items)), "aflopend")
        shifted = base[:5] + [zp_item(datetime.fromisoformat(base[4]["start_date"]) + timedelta(minutes=5), 4_000_000)] + base[5:]
        self.assertIsNone(build(zp_state(shifted)), "een kwartier dat niet precies na het vorige begint (overlap)")
        # twee reeksen met een gat ertussen
        two = zp_list(count=4) + zp_list(count=4, first=ZP_FIRST + timedelta(hours=3))
        self.assertIsNone(build(zp_state(two)))
        self.assertEqual(len(build(zp_state(base))["slots"]), 10, "zonder gat gaat het wel")

    def test_een_item_dat_geen_item_is_laat_geen_gat(self):
        base = zp_list(count=10)
        self.assertEqual(len(build(zp_state([*base[:4], None, 5, "tekst", [], *base[4:]]))["slots"]), 10)

    def test_een_onleesbaar_item_aan_de_rand_wordt_overgeslagen_in_het_midden_geeft_het_een_gat(self):
        """Hetzelfde gedrag als bij raw_today (een onleesbaar item wordt overgeslagen); het gat dat daardoor midden in de lijst ontstaat, houdt de hele lijst tegen: de portal weigert zo'n lijst."""
        good = build(zp_state(zp_list(count=10)))["slots"]
        self.assertEqual(len(good), 10)
        for name, make_bad in UNREADABLE_ITEMS:
            for index, expected in ((0, good[1:]), (9, good[:9]), (5, None)):
                items = zp_list(count=10)
                items[index] = make_bad(items[index])
                forecast = build(zp_state(items))
                if expected is None:
                    self.assertIsNone(forecast, f"{name} op plaats {index}: een gat, dus geen lijst")
                else:
                    self.assertEqual(forecast["slots"], expected, f"{name} op plaats {index}: overgeslagen")
            # een lijst met alleen onleesbare items geeft niets
            self.assertIsNone(build(zp_state([make_bad(item) for item in zp_list(count=6)])), name)

    def test_het_bereik_van_de_portal_voor_een_bedrag_is_inclusief(self):
        start = datetime(2026, 11, 14, 7, 45, tzinfo=AMS_WINTER)
        self.assertEqual(build(zp_state(zp_pair(start, 50_000_000)))["slots"][0]["value"], 5.0)
        self.assertEqual(build(zp_state(zp_pair(start, -10_000_000)))["slots"][0]["value"], -1.0)
        self.assertIsNone(build(zp_state(zp_pair(start, 50_000_001))), "het eerste item valt buiten het bereik en wordt overgeslagen: een slot is te weinig")
        self.assertIsNone(build(zp_state(zp_pair(start, -10_000_001))))

    # --- geen attribuut, geen lijst ---

    def test_geen_lijst_geen_forecast(self):
        self.assertIsNone(build(zp_state(MISSING)))
        for rommel in (None, [], (), "tekst", 5, {"start_date": "2026-11-14T07:45:00+01:00"}, {}, True):
            self.assertIsNone(build(zp_state(rommel)), repr(rommel))
        self.assertIsNone(build(zp_state(zp_list(), entity_id="device_tracker.auto")))
        self.assertIsNone(build(zp_state(zp_list()), prefix="binary_sensor."))
        self.assertIsNone(build(None))

    def test_een_ander_attribuut_telt_niet(self):
        state_ = state(ZP_ENTITY, ZP_STATE, None, unit_of_measurement="€/kWh", forecasts=zp_list(), prices=zp_list(), raw_forecast=zp_list())
        self.assertIsNone(build(state_))

    # --- beide formaten op een sensor ---

    def test_raw_today_en_raw_tomorrow_gaan_voor_op_forecast(self):
        forecast = build(zp_state(zp_list(), unit="EUR/kWh", raw_today=TODAY, raw_tomorrow=TOMORROW))
        self.assertEqual(forecast["attributes"], "raw_today+raw_tomorrow")
        self.assertEqual(len(forecast["slots"]), 192)
        self.assertEqual(forecast["slots"][0], {"start": "2026-11-13T00:00:00+01:00", "value": 0.2})
        self.assertEqual(build(zp_state(zp_list(), raw_today=TODAY))["attributes"], "raw_today")
        self.assertEqual(build(zp_state(zp_list(), raw_tomorrow=TOMORROW))["attributes"], "raw_tomorrow")

    def test_raw_voorrang_geldt_ook_met_een_eenheid_die_bij_forecast_niet_mag(self):
        forecast = build(zp_state(zp_list(), unit="ct/kWh", raw_today=TODAY))
        self.assertEqual(forecast["attributes"], "raw_today")
        self.assertEqual(forecast["unitOfMeasurement"], "ct/kWh", "bij raw_today blijft de eenheid van de sensor zoals nu")

    def test_zonder_bruikbare_raw_items_valt_de_sensor_terug_op_forecast(self):
        expected = build(zp_state(zp_list()))
        self.assertEqual(expected["attributes"], "forecast")
        for raw in ([], [None, 5, "tekst"], [{"value": 0.5}], [{"start": "gisteren", "value": 0.5}], "geen lijst", None):
            forecast = build(zp_state(zp_list(), raw_today=raw, raw_tomorrow=raw))
            self.assertEqual(forecast, expected, repr(raw))
        self.assertIsNone(build(zp_state([], raw_today=[], raw_tomorrow=[])))
        self.assertIsNone(build(zp_state(zp_list(), unit="ct/kWh", raw_today=[], raw_tomorrow=[])), "de eenheid maakt de lijst onbruikbaar, de raw-attributen zijn leeg")

    def test_het_label_is_een_naam_die_de_portal_leest(self):
        for forecast in (build(zp_state(zp_list())), build(price_state(TODAY, TOMORROW)), build(price_state(TODAY))):
            self.assertRegex(forecast["attributes"], r"^[a-z0-9_]+(\+[a-z0-9_]+)*$", "alleen kleine letters, cijfers, _ en +: nooit een entity-id")

    # --- de omschakeling van de klok ---

    def test_de_dag_van_de_omschakeling_met_tekst(self):
        """25 oktober 2026: de verschuiving gaat van +02:00 naar +01:00 midden in de lijst; 02:45 +02:00 en 02:00 +01:00 liggen een kwartier uit elkaar, het is dezelfde lijst zonder gat."""
        base = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)  # 00:00 +02:00
        items = []
        for i in range(100):
            start = (base + timedelta(minutes=15 * i)).astimezone(AMS_SUMMER if i < 12 else AMS_WINTER)
            end = (base + timedelta(minutes=15 * (i + 1))).astimezone(AMS_SUMMER if i + 1 < 12 else AMS_WINTER)
            items.append({**zp_item(start, 3_000_000 + i), "start_date": start.isoformat(), "end_date": end.isoformat()})
        self.assertEqual((items[11]["start_date"], items[11]["end_date"]), ("2026-10-25T02:45:00+02:00", "2026-10-25T02:00:00+01:00"))
        slots = build(zp_state(items))["slots"]
        self.assertEqual(len(slots), 100)
        self.assertEqual((slots[11]["start"], slots[12]["start"]), ("2026-10-25T02:45:00+02:00", "2026-10-25T02:00:00+01:00"))
        self.assertEqual(len({s["start"] for s in slots}), 100)

    def test_de_dag_van_de_omschakeling_met_een_tijdzone_waarbij_python_met_de_wandtijd_rekent(self):
        """Dezelfde dag met datetime-objecten van een tijdzone die aan beide kanten hetzelfde object is: Python trekt dan de WANDtijden af (02:00 min 02:45 is min 45 minuten). Een vergelijking in UTC rekent goed."""

        class Overgang(tzinfo):
            def utcoffset(self, dt):
                wall = dt.replace(tzinfo=None)
                if wall < datetime(2026, 10, 25, 2, 0):
                    return timedelta(hours=2)
                if wall < datetime(2026, 10, 25, 3, 0):
                    return timedelta(hours=1 if dt.fold else 2)
                return timedelta(hours=1)

            def dst(self, dt):
                return timedelta(0)

            def tzname(self, dt):
                return "Overgang"

            def fromutc(self, dt):
                naive = dt.replace(tzinfo=None)
                if naive < datetime(2026, 10, 25, 1, 0):
                    return (naive + timedelta(hours=2)).replace(tzinfo=self)
                return (naive + timedelta(hours=1)).replace(tzinfo=self, fold=1 if naive < datetime(2026, 10, 25, 2, 0) else 0)

        tz = Overgang()
        base = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
        items = []
        for i in range(100):
            start = (base + timedelta(minutes=15 * i)).astimezone(tz)
            end = (base + timedelta(minutes=15 * (i + 1))).astimezone(tz)
            items.append(zp_with(zp_item(start, 3_000_000 + i), start_date=start, end_date=end))
        self.assertEqual(items[11]["end_date"] - items[11]["start_date"], timedelta(minutes=-45), "het uitgangspunt: Python rekent hier met de wandtijd en komt op min 45 minuten")
        slots = build(zp_state(items))["slots"]
        self.assertEqual(len(slots), 100)
        self.assertEqual((slots[11]["start"], slots[12]["start"]), ("2026-10-25T02:45:00+02:00", "2026-10-25T02:00:00+01:00"))

    # --- grenzen ---

    def test_hooguit_max_slots_items_ook_bij_forecast(self):
        many = zp_list(count=500)
        self.assertEqual(len(build(zp_state(many))["slots"]), MAX_SLOTS)
        forecast = build(zp_state(many), max_slots=10)
        self.assertEqual(len(forecast["slots"]), 10)
        self.assertEqual(forecast["slots"][-1]["start"], "2026-11-13T09:15:00+01:00", "de eerste items, in de volgorde van de sensor")
        self.assertEqual(len(build(zp_state(zp_list(count=MAX_SLOTS)))["slots"]), MAX_SLOTS, "precies op de grens: alles")

    def test_het_resultaat_is_geldige_json_zonder_nan_of_infinity(self):
        items = zp_list(count=10)
        items[0] = zp_with(items[0], price_tax_included={"amount": float("nan")})
        items[9] = zp_with(items[9], price_tax_included={"amount": float("inf")})
        forecast = build(zp_state(items))
        text = json.dumps(forecast, allow_nan=False)  # gooit bij NaN of Infinity: de portal zou de HELE push weigeren
        self.assertEqual(len(json.loads(text)["slots"]), 8, "NaN en oneindig aan de rand zijn overgeslagen")
        items[4] = zp_with(items[4], price_tax_included={"amount": float("nan")})
        self.assertIsNone(build(zp_state(items)), "NaN in het midden: een gat, dus geen lijst")

    def test_het_bekijkplafond_geldt_ook_voor_forecast(self):
        rommel = ScanCeilingTests.Teller([None] * 1_000_000)
        self.assertIsNone(build(zp_state(rommel)))
        self.assertLessEqual(rommel.gezien, MAX_SLOTS * payload.PRICE_FEED_SCAN_FACTOR)
        teller = ScanCeilingTests.Teller(zp_list())
        self.assertEqual(len(build(zp_state(teller))["slots"]), 164)
        self.assertEqual(teller.gezien, 164)

    def test_het_bekijkplafond_wordt_gedeeld_met_raw_today_en_raw_tomorrow(self):
        plafond = MAX_SLOTS * payload.PRICE_FEED_SCAN_FACTOR
        # raw-rommel die het hele plafond opmaakt: forecast wordt niet meer bekeken
        raw = ScanCeilingTests.Teller([None] * plafond)
        forecast_items = ScanCeilingTests.Teller(zp_list())
        self.assertIsNone(build(zp_state(forecast_items, raw_today=raw)))
        self.assertEqual(forecast_items.gezien, 0)
        # een stukje raw-rommel: forecast krijgt de rest van het plafond
        raw = ScanCeilingTests.Teller([None] * 100)
        forecast_items = ScanCeilingTests.Teller(zp_list())
        self.assertEqual(len(build(zp_state(forecast_items, raw_today=raw))["slots"]), 164)
        self.assertLessEqual(raw.gezien + forecast_items.gezien, plafond)

    def test_rommel_in_forecast_stopt_niets(self):
        class KapotItem:
            def get(self, _key, _default=None):
                raise ValueError("kapot item")

        errors = []
        result = payload.price_forecast_to_send(lambda _e: zp_state([KapotItem()]), ZP_ENTITY, PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL, None, errors.append)
        self.assertEqual(result, (None, None))
        self.assertEqual([type(e).__name__ for e in errors], ["ValueError"])
        year_one = [zp_item(datetime(1, 1, 1, 0, 0, tzinfo=AMS_WINTER), 4_000_000)]
        self.assertIsNone(build(zp_state(year_one)), "een jaartal dat niet naar UTC kan: onleesbaar, geen fout")


class ZonneplanSendTests(unittest.TestCase):
    def send(self, price_state_, entity=ZP_ENTITY, last_signature=None, last_sent=None, now=5000.0):
        return payload.price_forecast_to_send(lambda _entity: price_state_, entity, PREFIX, MAX_SLOTS, last_signature, last_sent, now, RESEND, MIN_INTERVAL)

    def test_een_portal_die_niets_noemt_laat_niets_het_huis_verlaten(self):
        """Zonder priceEntity (een oudere portal, een account zonder prijslijst, null) wordt de toestand van de sensor niet eens gelezen, laat staan verstuurd."""

        def boom(_entity):
            raise AssertionError("de toestand van de prijssensor mag niet gelezen worden zonder priceEntity")

        for response in ({"ok": True, "mapped": [ZP_ENTITY]}, {"ok": True, "mapped": [ZP_ENTITY], "priceEntity": None}, {"ok": True, "mapped": [ZP_ENTITY], "priceEntity": ""}):
            entity = payload.update_price_entity(None, response)
            self.assertIsNone(entity)
            self.assertEqual(payload.price_forecast_to_send(boom, entity, PREFIX, MAX_SLOTS, None, None, 5000.0, RESEND, MIN_INTERVAL), (None, None))
        # ook een onleesbaar antwoord als allereerste antwoord: nog niets gehoord, dus niets
        self.assertIsNone(payload.update_price_entity(None, "<html>Bad gateway</html>"))
        # en de standen van die push zijn die van 1.1.0: alleen de gekoppelde sensor, zonder zijn attributen
        states = [zp_state(zp_list())]
        sent = payload.states_to_send(states, {ZP_ENTITY}, False, PREFIX)
        self.assertEqual([s["entityId"] for s in sent], [ZP_ENTITY])
        self.assertNotIn("forecast", json.dumps(sent))
        self.assertNotIn("price_tax", json.dumps(sent))

    def test_met_priceEntity_de_zonneplan_lijst_en_zijn_handtekening(self):
        forecast, signature = self.send(zp_state(zp_list()))
        self.assertEqual(len(forecast["slots"]), 164)
        self.assertEqual(signature, payload.price_forecast_signature(forecast))
        self.assertTrue(signature.startswith(f"{ZP_ENTITY}|EUR/kWh|forecast#"))
        # daarna niet bij elke push
        self.assertEqual(self.send(zp_state(zp_list()), last_signature=signature, last_sent=5000.0, now=5030.0), (None, None))
        self.assertIsNotNone(self.send(zp_state(zp_list()), last_signature=signature, last_sent=5000.0, now=5000.0 + RESEND)[0])

    def test_een_andere_prijs_geeft_een_andere_handtekening(self):
        _, a = self.send(zp_state(zp_list()))
        changed = zp_list()
        changed[50] = zp_with(changed[50], price_tax_included={"amount": 3_999_999})
        _, b = self.send(zp_state(changed))
        self.assertNotEqual(a, b)
        _, c = self.send(zp_state(zp_list(text=False)))
        self.assertEqual(a, c, "datetime-objecten of tekst: dezelfde inhoud")
        shorter = zp_list()[:-1]
        self.assertNotEqual(a, self.send(zp_state(shorter))[1])

    def test_de_prijssensor_zonder_bruikbare_lijst_geeft_niets_en_de_rest_van_de_push_blijft(self):
        self.assertEqual(self.send(zp_state(MISSING)), (None, None))
        self.assertEqual(self.send(None), (None, None))


# --- wat de portal altijd weigert gaat niet mee: te veel slots, te weinig slots, een begintijd naast het kwartier, een begintijd van meer dan 64 tekens ---


def text_items(items):
    """De items van day_items met begin- en eindtijd als ISO-tekst (zoals een sensor ze ook kan geven)."""
    return [{**item, "start": item["start"].isoformat(), "end": item["end"].isoformat()} for item in items]


def raw_state(first: datetime, count: int = 6, text: bool = False):
    items = day_items(first, count)
    return price_state(text_items(items) if text else items)


def forecast_state(first: datetime, count: int = 6, text: bool = True):
    return zp_state(zp_list(count=count, first=first, text=text))


UTC = timezone.utc
# Begintijden die de portal niet leest: niet op een kwartiergrens in UTC, met seconden of een deel van een seconde, of met een UTC-verschil dat niet uit hele minuten bestaat.
OFF_GRID = [
    ("7 minuten naast het kwartier", datetime(2026, 11, 13, 7, 7, tzinfo=UTC)),
    ("een minuut voor het kwartier", datetime(2026, 11, 13, 6, 59, tzinfo=UTC)),
    ("een minuut na het kwartier", datetime(2026, 11, 13, 7, 16, tzinfo=UTC)),
    ("30 seconden", datetime(2026, 11, 13, 7, 0, 30, tzinfo=UTC)),
    ("een halve seconde", datetime(2026, 11, 13, 7, 0, 0, 500_000, tzinfo=UTC)),
    ("een microseconde", datetime(2026, 11, 13, 7, 0, 0, 1, tzinfo=UTC)),
    ("op een kwartier in de eigen tijd maar niet in UTC", datetime(2026, 11, 13, 12, 45, tzinfo=timezone(timedelta(hours=5, minutes=20)))),
    ("een UTC-verschil met seconden (in UTC wel op het kwartier)", datetime(2026, 11, 13, 7, 0, 30, tzinfo=timezone(timedelta(hours=1, seconds=30)))),
]
# Begintijden die de portal wel leest, elk met zijn eigen UTC-verschil.
ON_GRID = [
    ("UTC", datetime(2026, 11, 13, 7, 0, tzinfo=UTC)),
    ("Amsterdam in de winter", datetime(2026, 11, 13, 8, 0, tzinfo=AMS_WINTER)),
    ("Amsterdam in de zomer", datetime(2026, 10, 24, 9, 0, tzinfo=AMS_SUMMER)),
    ("+05:30", datetime(2026, 11, 13, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))),
    ("-03:30", datetime(2026, 11, 13, 3, 30, tzinfo=timezone(-timedelta(hours=3, minutes=30)))),
    ("een UTC-verschil dat zelf niet op een kwartier staat, maar de tijd in UTC wel", datetime(2026, 11, 13, 12, 20, tzinfo=timezone(timedelta(hours=5, minutes=20)))),
]


class PortalLimitTests(unittest.TestCase):
    # --- het maximum aantal slots (de portal weigert bij meer dan 288 de hele lijst) ---

    def test_de_grens_is_die_van_de_portal_drie_dagen_van_96_kwartieren(self):
        self.assertEqual(const.PRICE_FEED_MAX_SLOTS, 288)
        self.assertEqual(const.PRICE_FEED_MAX_SLOTS, 3 * (timedelta(days=1) // payload.PRICE_QUARTER))
        self.assertEqual(payload.PRICE_FEED_MIN_SLOTS, 2)

    def test_een_langere_lijst_wordt_afgekapt_op_de_grens_en_gaat_nooit_met_meer_dan_288_slots_mee(self):
        first = datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER)
        for count in (287, 288, 289, 320, 400, 500):
            expected = min(count, 288)
            raw = build(price_state(day_items(first, count)))
            zonneplan = build(zp_state(zp_list(count=count)))
            for name, feed in (("raw", raw), ("forecast", zonneplan)):
                self.assertEqual(len(feed["slots"]), expected, f"{name} met {count} items")
                self.assertLessEqual(len(feed["slots"]), 288, f"{name} met {count} items: de portal weigert meer dan 288")
        # de eerste items blijven, in de volgorde van de sensor
        self.assertEqual(build(price_state(day_items(first, 320)))["slots"][287]["start"], (first + timedelta(minutes=15 * 287)).isoformat())

    # --- minstens twee slots ---

    def test_een_lijst_met_minder_dan_twee_slots_gaat_niet_mee_met_twee_wel(self):
        first = datetime(2026, 11, 13, 7, 0, tzinfo=AMS_WINTER)
        for count, expected in ((0, None), (1, None), (2, 2), (3, 3)):
            raw = build(price_state(day_items(first, count)))
            zonneplan = build(zp_state(zp_list(count=count, first=first)))
            for name, feed in (("raw", raw), ("forecast", zonneplan)):
                if expected is None:
                    self.assertIsNone(feed, f"{name} met {count} slot(s): de portal eist er minstens twee")
                else:
                    self.assertEqual(len(feed["slots"]), expected, f"{name} met {count} slots")

    def test_een_raw_lijst_met_een_slot_laat_de_forecast_van_dezelfde_sensor_toe_en_anders_niets(self):
        first = datetime(2026, 11, 13, 7, 0, tzinfo=AMS_WINTER)
        one = day_items(first, 1)
        self.assertIsNone(build(price_state(one)))
        feed = build(price_state(one, forecast=zp_list(count=6, first=first)))
        self.assertEqual((feed["attributes"], len(feed["slots"])), ("forecast", 6), "de raw lijst is te kort voor de portal: de forecast van dezelfde sensor gaat mee")
        # een raw lijst van twee slots gaat voor op de forecast, zoals altijd
        self.assertEqual(build(price_state(day_items(first, 2), forecast=zp_list(count=6, first=first)))["attributes"], "raw_today")

    # --- een begintijd op een kwartiergrens in UTC ---

    def test_een_begintijd_die_niet_op_een_kwartiergrens_in_utc_ligt_geeft_geen_lijst(self):
        for name, first in OFF_GRID:
            for text in (False, True):
                self.assertIsNone(build(raw_state(first, text=text)), f"raw, {name}, als tekst: {text}")
                self.assertIsNone(build(forecast_state(first, text=text)), f"forecast, {name}, als tekst: {text}")

    def test_een_begintijd_op_een_kwartiergrens_in_utc_gaat_mee_met_zijn_eigen_utc_verschil(self):
        for name, first in ON_GRID:
            for text in (False, True):
                for format_name, state_ in (("raw", raw_state(first, text=text)), ("forecast", forecast_state(first, text=text))):
                    feed = build(state_)
                    self.assertEqual(len(feed["slots"]), 6, f"{format_name}, {name}, als tekst: {text}")
                    self.assertEqual(feed["slots"][0]["start"], first.isoformat(), f"{format_name}, {name}: de begintijd houdt zijn verschuiving")

    def test_een_enkele_begintijd_naast_het_kwartier_houdt_de_hele_lijst_tegen_niet_alleen_dat_slot(self):
        items = day_items(datetime(2026, 11, 13, 7, 0, tzinfo=UTC), 8)
        items[5] = quarter(datetime(2026, 11, 13, 8, 22, tzinfo=UTC), 0.5)
        self.assertIsNone(build(price_state(items)), "de portal weigert de hele lijst: dan sturen we hem niet")
        self.assertEqual(len(build(price_state(day_items(datetime(2026, 11, 13, 7, 0, tzinfo=UTC), 8)))["slots"]), 8)

    def test_een_raw_lijst_naast_het_kwartier_laat_de_forecast_van_dezelfde_sensor_toe(self):
        off = datetime(2026, 11, 13, 7, 7, tzinfo=UTC)
        feed = build(price_state(day_items(off, 6), forecast=zp_list(count=6, first=datetime(2026, 11, 13, 7, 0, tzinfo=UTC))))
        self.assertEqual((feed["attributes"], len(feed["slots"])), ("forecast", 6))


class StartLengthTests(unittest.TestCase):
    """Een begintijd is hooguit 64 tekens (ook de grens van de portal): een langere tekst is onleesbaar en wordt niet eens ontleed."""

    GOOD = "2026-11-13T00:00:00+01:00"

    class Spy(datetime):
        lengths: list[int] = []

        @classmethod
        def fromisoformat(cls, text):
            StartLengthTests.Spy.lengths.append(len(text))
            return super().fromisoformat(text)

    def setUp(self):
        StartLengthTests.Spy.lengths = []

    def test_een_tekst_van_hooguit_64_tekens_wordt_gelezen_een_langere_niet(self):
        self.assertEqual(payload.PRICE_FEED_MAX_START_LENGTH, 64)
        self.assertEqual(len(self.GOOD.ljust(64)), 64)
        self.assertIsNotNone(payload._price_moment(self.GOOD.ljust(64)))
        self.assertIsNotNone(payload._price_moment(" " * (64 - len(self.GOOD)) + self.GOOD))
        self.assertIsNone(payload._price_moment(self.GOOD.ljust(65)))
        self.assertIsNone(payload._price_moment(" " + self.GOOD.ljust(64)))
        self.assertIsNone(payload._price_moment(self.GOOD + "0" * 100))

    def test_een_tekst_van_1_mb_als_begintijd_wordt_niet_ontleed(self):
        big = self.GOOD + " " * 1_000_000
        with patch.object(payload, "datetime", self.Spy):
            self.assertIsNone(payload._price_moment(big))
        self.assertEqual(StartLengthTests.Spy.lengths, [], "de ontleding is niet aangeroepen")
        # ook een lange tekst zonder tijd erin wordt niet ontleed: de lengte telt, de inhoud niet
        with patch.object(payload, "datetime", self.Spy):
            self.assertIsNone(payload._price_moment("x" * 1_000_000))
        self.assertEqual(StartLengthTests.Spy.lengths, [])

    def test_een_enorme_begintijd_in_een_lijst_wordt_overgeslagen_zonder_ontleding_bij_beide_formaten(self):
        big = self.GOOD + " " * 1_000_000
        first = datetime(2026, 11, 13, 0, 0, tzinfo=AMS_WINTER)
        raw = text_items(day_items(first, 4))
        raw.insert(2, {"start": big, "end": big, "value": 0.9})
        forecast_items = zp_list(count=4, first=first, text=True)
        forecast_items.insert(2, zp_with(forecast_items[2], start_date=big))
        with patch.object(payload, "datetime", self.Spy):
            raw_feed = build(price_state(raw))
            forecast_feed = build(zp_state(forecast_items))
        self.assertEqual(len(raw_feed["slots"]), 4, "het item met de enorme begintijd is overgeslagen")
        self.assertEqual(len(forecast_feed["slots"]), 4)
        self.assertTrue(StartLengthTests.Spy.lengths, "de gewone begintijden zijn wel ontleed")
        self.assertLessEqual(max(StartLengthTests.Spy.lengths), 64, "er is nooit een tekst van meer dan 64 tekens ontleed")


class FeedFieldsTests(unittest.TestCase):
    """De README noemt wat er in de lijst staat: per kwartier alleen de begintijd en de prijs, bovenaan de naam van de sensor, de eenheid en de naam van het gelezen attribuut. Dit zijn de velden die er werkelijk zijn."""

    def test_bovenaan_de_lijst_de_sensor_de_eenheid_en_het_attribuut_en_per_kwartier_alleen_begintijd_en_prijs(self):
        for name, feed in (("raw", build(price_state(TODAY, TOMORROW))), ("forecast", build(zp_state(zp_list())))):
            self.assertEqual(set(feed), {"entityId", "unitOfMeasurement", "attributes", "slots"}, name)
            self.assertIsInstance(feed["entityId"], str)
            self.assertIn(feed["unitOfMeasurement"], ("EUR/kWh",), name)
            self.assertIn(feed["attributes"], ("raw_today+raw_tomorrow", "forecast"), name)
            for slot in feed["slots"]:
                self.assertEqual(set(slot), {"start", "value"}, f"{name}: per kwartier alleen de begintijd en de prijs")


if __name__ == "__main__":
    unittest.main()