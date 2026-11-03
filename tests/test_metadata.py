"""De bestanden om de integratie heen (manifest, vertalingen, hacs.json): klopt wat Home Assistant en HACS ervan lezen. Draaien zonder Home Assistant: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION = REPO / "custom_components" / "ampwise_push"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        out |= keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}"}
    return out


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load(INTEGRATION / "manifest.json")
        self.const = (INTEGRATION / "const.py").read_text(encoding="utf-8")

    def test_domein_en_map(self):
        self.assertEqual(self.manifest["domain"], "ampwise_push")
        self.assertIn('DOMAIN = "ampwise_push"', self.const)
        self.assertEqual(self.manifest["domain"], INTEGRATION.name, "de map heet zoals het domein")

    def test_versie_is_dezelfde_als_in_de_code(self):
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertIn(f'INTEGRATION_VERSION = "{self.manifest["version"]}"', self.const)

    def test_alleen_wat_de_integratie_werkelijk_is(self):
        self.assertTrue(self.manifest["config_flow"])
        self.assertEqual(self.manifest["iot_class"], "cloud_push", "hij duwt standen naar de cloud en maakt geen eigen entiteiten")
        self.assertEqual(self.manifest["integration_type"], "service")
        self.assertEqual(self.manifest["requirements"], [], "geen extra Python-pakketten: aiohttp en voluptuous zijn er al in Home Assistant")
        self.assertNotIn("dependencies", self.manifest)

    def test_geen_import_van_pakketten_buiten_home_assistant_en_de_standaardbibliotheek(self):
        allowed = {"__future__", "logging", "time", "datetime", "typing", "aiohttp", "voluptuous", "homeassistant"}
        for path in INTEGRATION.glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^(?:from|import)\s+([A-Za-z_]\w*)", line)
                if m:
                    self.assertIn(m.group(1), allowed, f"{path.name}: {line}")

    def test_hacs_json(self):
        hacs = load(REPO / "hacs.json")
        self.assertEqual(hacs["name"], "Ampwise")


class TranslationTests(unittest.TestCase):
    def test_nl_en_en_strings_hebben_dezelfde_sleutels(self):
        strings = load(INTEGRATION / "strings.json")
        nl = load(INTEGRATION / "translations" / "nl.json")
        en = load(INTEGRATION / "translations" / "en.json")
        self.assertEqual(keys(strings), keys(en))
        self.assertEqual(keys(nl), keys(en))
        self.assertEqual(nl, strings, "strings.json is de Nederlandse tekst; translations/nl.json is dezelfde tekst")

    def test_de_teksten_voor_de_velden_en_fouten_die_de_config_flow_gebruikt_bestaan(self):
        en = load(INTEGRATION / "translations" / "en.json")
        flow = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        for field in ("api_key", "ingest_url", "push_interval"):
            self.assertIn(field, en["config"]["step"]["user"]["data"])
        used = re.findall(r'errors\["base"\] = "(\w+)"', flow)
        self.assertTrue(used, "de config flow zet een fout")
        for error in used:
            self.assertIn(error, en["config"]["error"], error)
        self.assertIn("already_configured", en["config"]["abort"])

    def test_geen_lege_teksten(self):
        for name in ("strings.json", "translations/en.json", "translations/nl.json"):
            data = load(INTEGRATION / name)
            for key in keys(data):
                node = data
                for part in key.split("."):
                    node = node[part]
                self.assertTrue(str(node).strip(), f"{name}: {key}")


class SeparationTests(unittest.TestCase):
    """De pure logica (payload.py) kent Home Assistant niet: zo blijft ze los te testen en kan er later een stuurdeel naast zonder dat het filter erin verstrikt raakt."""

    def test_payload_importeert_geen_home_assistant(self):
        source = (INTEGRATION / "payload.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(?:from|import)\s+(?:homeassistant|aiohttp)")

    def test_geen_merk_of_gielz_in_de_integratie(self):
        for path in INTEGRATION.glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for merk in ("gielz", "zendure", "solix", "anker"):
                self.assertNotIn(merk, text, f"{path.name} noemt {merk}")


if __name__ == "__main__":
    unittest.main()
