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
]


class CatalogTests(unittest.TestCase):
    def test_alleen_sensoren_en_nooit_een_stand(self):
        catalog = payload.build_catalog(STATES, PREFIX)
        self.assertEqual([c["entityId"] for c in catalog], ["sensor.zon", "sensor.telefoon_batterij", "sensor.stuk"])
        for entry in catalog:
            self.assertNotIn("state", entry)
            self.assertNotIn("lastUpdated", entry)
        dump = json.dumps(catalog)
        self.assertNotIn('"state"', dump)
        self.assertNotIn("1500", dump)

    def test_naam_type_en_eenheid(self):
        zon = payload.build_catalog(STATES, PREFIX)[0]
        self.assertEqual(zon, {"entityId": "sensor.zon", "unitOfMeasurement": "W", "deviceClass": "power", "friendlyName": "Zon"})
        stuk = payload.build_catalog(STATES, PREFIX)[2]
        self.assertIsNone(stuk["unitOfMeasurement"])


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

    def test_een_portal_zonder_lijst_krijgt_alles_zoals_voorheen(self):
        self.assertEqual(len(payload.build_states(STATES, None, PREFIX)), 3)

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


class VersionTests(unittest.TestCase):
    def test_manifest_en_constante_hebben_dezelfde_versie(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        const = (ROOT / "const.py").read_text(encoding="utf-8")
        self.assertIn(f'INTEGRATION_VERSION = "{manifest["version"]}"', const)


if __name__ == "__main__":
    unittest.main()
