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


class CiTests(unittest.TestCase):
    """De CI (.github/workflows/test.yml) draait op de versie van Home Assistant die in productie staat; deze tests houden de bestanden eromheen bij elkaar."""

    def setUp(self):
        self.workflow = (REPO / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.requirements_ci = (REPO / "requirements_test_ci.txt").read_text(encoding="utf-8")
        self.requirements_local = (REPO / "requirements_test.txt").read_text(encoding="utf-8")

    def test_ci_gebruikt_de_testbibliotheek_van_home_assistant_2026_10_4_op_python_3_14(self):
        self.assertIn("pytest-homeassistant-custom-component==0.13.375", self.requirements_ci)
        self.assertIn('python-version: "3.14"', self.workflow)
        self.assertIn("requirements_test_ci.txt", self.workflow)
        self.assertIn("pip install -r requirements_test_ci.txt", self.workflow)

    def test_de_pin_op_pycares_van_home_assistant_2025_hoort_niet_in_de_ci(self):
        self.assertNotIn("pycares", [l.split("==")[0].strip() for l in self.requirements_ci.splitlines() if l.strip() and not l.lstrip().startswith("#")])
        self.assertIn("pycares==4.5.0", self.requirements_local)

    def test_de_lokale_opzet_blijft_op_python_3_12(self):
        self.assertIn("pytest-homeassistant-custom-component==0.13.205", self.requirements_local)

    def test_de_workflow_draait_bij_een_pull_request_en_heeft_alleen_leesrechten(self):
        self.assertRegex(self.workflow, r"(?m)^on:\n  push:\n    branches: \[main\]\n  pull_request:")
        self.assertRegex(self.workflow, r"(?m)^permissions:\n  contents: read$")

    def test_de_workflow_draait_de_ha_tests_en_de_berichtentests(self):
        self.assertIn("python -m pytest tests", self.workflow)
        self.assertIn("python -m unittest discover -s tests -t .", self.workflow)


class PublicatieTests(unittest.TestCase):
    """Wat hassfest en HACS van de repository vragen. De controles zelf draaien alleen in GitHub (.github/workflows/validate.yml); deze tests houden de bestanden eronder bij elkaar."""

    def test_manifest_heeft_de_sleutels_die_hacs_vraagt_en_staat_gesorteerd_zoals_hassfest_wil(self):
        manifest = load(INTEGRATION / "manifest.json")
        for key in ("domain", "documentation", "issue_tracker", "codeowners", "name", "version"):
            self.assertIn(key, manifest, key)
        self.assertTrue(manifest["documentation"].startswith("https://"))
        self.assertTrue(manifest["issue_tracker"].startswith("https://"))
        rest = sorted(k for k in manifest if k not in ("domain", "name"))
        self.assertEqual(list(manifest), ["domain", "name", *rest], "hassfest: eerst domain en name, daarna alfabetisch")

    def test_de_licentie_is_mit_en_het_merk_valt_er_in_de_readme_buiten(self):
        self.assertTrue((REPO / "LICENSE").read_text(encoding="utf-8").startswith("MIT License"))
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn('De naam en het merk "Ampwise" en het logo vallen er niet onder', readme)

    def test_de_validatie_workflow_heeft_alleen_leesrechten_en_pint_elke_actie_op_een_commit(self):
        workflow = (REPO / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^permissions:\n  contents: read$")
        actions = re.findall(r"(?m)^\s+- uses: (\S+)", workflow)
        self.assertEqual(len(actions), 3, "checkout, hassfest en de HACS-controle")
        for action in actions:
            self.assertRegex(action, r"@[0-9a-f]{40}$", f"{action} staat niet vast op een commit")
        self.assertIn("home-assistant/actions/hassfest@", workflow)
        self.assertIn("hacs/action@", workflow)
        self.assertIn("category: integration", workflow)
