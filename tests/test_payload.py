"""Tests voor de berichten naar de portal (payload.py). Draaien zonder Home Assistant: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "ampwise_push"
spec = importlib.util.spec_from_file_location("ampwise_payload", ROOT / "payload.py")
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)

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
        """Dezelfde tabel als CASES in tests/energyRelevance.spec.ts van de portal (de gas-gevallen): het type gas telt in elke eenheid, de eenheid m³ of m3 telt ook zonder type."""
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


if __name__ == "__main__":
    unittest.main()
