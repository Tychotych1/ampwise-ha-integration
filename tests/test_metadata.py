"""De bestanden om de integratie heen (manifest, vertalingen, hacs.json): klopt wat Home Assistant en HACS ervan lezen. Draaien zonder Home Assistant: python -m unittest discover -s tests -t ."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import unittest
from datetime import timedelta

REPO = pathlib.Path(__file__).resolve().parents[1]
INTEGRATION = REPO / "custom_components" / "ampwise_push"


def load_module(name: str):
    """const.py of payload.py los geladen (zonder Home Assistant): de werkelijke waarden van de constanten."""
    spec = importlib.util.spec_from_file_location(f"ampwise_{name}_metadata", INTEGRATION / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# SHA-256 (hex) van interne namen van de portal (kleine letters), gegroepeerd naar het aantal tekens van de naam. De namen zelf staan hier bewust niet: een publieke repo hoort ze niet op te sommen.
_INTERNAL_NAME_HASHES = {
    4: {"f181bbb3066293425edf0bfbba5197f7802dd52823fc174c4db1678a43544e61"},
    7: {"fef4cb2b3b6195c9f562cd5a5ec4191cc96979d47352c7df10df909e89033b1a", "244b8435061420f6b2887681bbe2d24b18fc8f790a75c5bf16937bb8417e651a"},
    10: {"66fa4e7b1783ca8968aaf4050748b444e8edea52ebdb0e4b73f50692d3677c16"},
    12: {"d681f7421bdfc347df6043af0e3651363b559846ae15ca177ade0475f2d4aa38", "f5d9fb35fd25c10521fb1e1c4664685523e1e89464690306daf65fdc6e5fb427"},
}


def internal_names_in(text: str) -> set[str]:
    """De stukjes uit `text` (in kleine letters, binnen een woord van letters en cijfers) waarvan de hash die van een interne naam is; leeg als er geen is."""
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        for length, hashes in _INTERNAL_NAME_HASHES.items():
            for start in range(len(word) - length + 1):
                piece = word[start : start + length]
                if hashlib.sha256(piece.encode("utf-8")).hexdigest() in hashes:
                    found.add(piece)
    return found


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

    def test_de_versie_is_minstens_1_2_0_de_versie_met_de_prijslijst(self):
        major, minor, patch = (int(part) for part in self.manifest["version"].split("."))
        self.assertGreaterEqual((major, minor, patch), (1, 2, 0), "de portal vraagt de prijslijst vanaf 1.2.0; een lagere versie stuurt hem niet")

    def test_de_constanten_van_de_prijslijst_zijn_die_van_de_portal(self):
        """Dezelfde waarden als de portal verwacht: een herhaling na 30 minuten, hooguit een veranderde lijst per 6 minuten (de portal verwerkt er 12 per uur: zo blijft er marge), een eerste nieuwe poging na een minuut voor een lijst die niet aankwam en hooguit 288 regels per lijst (drie dagen van 96 kwartieren: meer weigert de portal helemaal)."""
        self.assertIn("PRICE_FEED_RESEND_SECONDS = 30 * 60", self.const)
        self.assertIn("PRICE_FEED_MIN_INTERVAL_SECONDS = 6 * 60", self.const)
        self.assertIn("PRICE_FEED_RETRY_SECONDS = 60", self.const)
        self.assertIn("PRICE_FEED_MAX_SLOTS = 288", self.const)

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

    def test_geen_merk_of_gielz_in_de_documentatie_en_de_teksten(self):
        for path in (REPO / "README.md", INTEGRATION / "strings.json", INTEGRATION / "manifest.json"):
            text = path.read_text(encoding="utf-8").lower()
            for merk in ("gielz", "zendure", "solix", "anker"):
                self.assertNotIn(merk, text, f"{path.name} noemt {merk}")

    def test_geen_interne_namen_van_de_portal_in_de_publieke_repo(self):
        """De integratie staat in een publieke repo: geen bestand daarin noemt interne onderdelen van de portal (een naam of een pad van een nog niet gepubliceerd onderdeel). De namen zelf staan hier niet:
        alleen hun hashes, en de vergelijking loopt over alle stukjes van elk woord (een naam in een langer woord telt ook)."""
        for path in sorted(p for p in REPO.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json", ".yml", ".txt", ".ini") and not set(p.parts) & {".git", ".venv", "__pycache__", ".pytest_cache"}):
            found = internal_names_in(path.read_text(encoding="utf-8"))
            self.assertFalse(found, f"{path.relative_to(REPO)} noemt een interne naam ({sorted(found)})")

    def test_de_bewaker_zelf_herkent_een_interne_naam_ook_in_een_langer_woord_of_een_pad(self):
        """De bewaker hierboven is alleen iets waard als hij echt aanslaat: de namen worden hier tijdens de toets uit stukjes gebouwd, zodat ze niet in de bron staan."""
        built = ["plan" + "ner", "schad" + "uwmodus", "he" + "ms", "koppel" + "vlak", "privacy" + "tekst", "ingest" + "limits"]
        for naam in built:
            self.assertTrue(internal_names_in(f"gewone tekst {naam} gewone tekst"), naam)
            self.assertTrue(internal_names_in(f"een voor{naam}achter en meer"), f"in een langer woord: {naam}")
            self.assertTrue(internal_names_in(f"src/lib/{naam.upper()}.ts"), f"hoofdletters en een pad: {naam}")
        self.assertTrue(internal_names_in("src/lib/he" + "ms/" + "koppel" + "vlak/prices.ts"))
        self.assertFalse(internal_names_in("De portal zegt welke sensor de prijssensor is en stuurt de lijst van vandaag en morgen mee."))
        self.assertFalse(internal_names_in(""))
    def test_de_readme_noemt_de_prijslijst_en_wat_er_niet_bij_elke_push_meegaat(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for woord in ("raw_today", "raw_tomorrow", "forecast", "Zonneplan", "prijssensor", "30 minuten"):
            self.assertIn(woord, readme)

    def test_de_readme_zegt_het_over_de_prijzen_van_de_prijssensor_zoals_de_eigenaar_het_vastlegde(self):
        """De zin van de eigenaar staat er letterlijk, en de oude zin (die het alleen over raw_today en raw_tomorrow had) niet meer."""
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        zin = (
            "Vanaf versie 1.2.0 stuurt de integratie ook de prijzen van je prijssensor mee: per kwartier de begintijd en de prijs. "
            "Dat gebeurt alleen als de portal daar voor jouw account om vraagt. Vraagt de portal er niet om, dan gaat er niets extra mee."
        )
        self.assertEqual(readme.count(zin), 1)
        self.assertNotIn("Sinds versie 1.2.0", readme)
        self.assertNotIn("De portal noemt in zijn antwoord welke sensor dat is", readme)


class ReadmeFactsTests(unittest.TestCase):
    """De getallen en beweringen in de alinea over de prijslijst van de README kloppen met de code: wijkt de README af van de constanten, dan wordt dit rood."""

    def setUp(self):
        self.readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.const = load_module("const")
        self.payload = load_module("payload")

    def test_het_maximum_aantal_regels_is_dat_van_de_code(self):
        self.assertEqual(re.findall(r"hooguit (\d+) regels", self.readme), [str(self.const.PRICE_FEED_MAX_SLOTS)])

    def test_de_tijden_zijn_die_van_de_code(self):
        self.assertEqual(self.const.PRICE_FEED_MIN_INTERVAL_SECONDS % 60, 0)
        self.assertEqual(self.const.PRICE_FEED_RESEND_SECONDS % 60, 0)
        self.assertEqual(
            re.findall(r"hooguit eens per (\d+) minuten", self.readme),
            [str(self.const.PRICE_FEED_MIN_INTERVAL_SECONDS // 60), str(self.const.PRICE_FEED_RESEND_SECONDS // 60)],
            "eerst de verandering van de lijst, dan de herhaling",
        )

    def test_vandaag_en_morgen_zijn_twee_dagen_van_96_kwartieren(self):
        self.assertEqual(self.payload.PRICE_QUARTER, timedelta(minutes=15))
        quarters_per_day = timedelta(days=1) // self.payload.PRICE_QUARTER
        self.assertEqual(quarters_per_day, 96)
        self.assertEqual(re.findall(r"vandaag en morgen zijn er (\d+)", self.readme), [str(2 * quarters_per_day)])
        self.assertLessEqual(2 * quarters_per_day, self.const.PRICE_FEED_MAX_SLOTS, "een gewone lijst past onder het maximum")

    def test_de_readme_zegt_wat_er_bovenaan_de_lijst_staat_en_dat_per_kwartier_alleen_de_begintijd_en_de_prijs_meegaan(self):
        self.assertIn("alleen de begintijd en de prijs mee", self.readme)
        self.assertIn("met bovenaan de lijst de naam van die ene sensor, de eenheid en de naam van het gelezen attribuut", self.readme)

    def test_de_readme_zegt_dat_de_push_op_het_versienummer_na_die_van_1_1_0_is(self):
        self.assertIn("de push is dan, op het versienummer na, gelijk aan die van versie 1.1.0", self.readme)

    def test_de_readme_zegt_dat_de_prijzen_van_morgen_komen_zodra_de_leverancier_ze_publiceert(self):
        self.assertIn("de prijzen van morgen komen zodra de leverancier ze publiceert, meestal in de loop van de middag", self.readme)
        self.assertNotIn("middernacht", self.readme, "bij de Zonneplan-integratie schuift de lijst niet om middernacht")

    def test_de_readme_zegt_dat_forecast_alleen_de_terugval_is(self):
        self.assertIn("`raw_today` en `raw_tomorrow`", self.readme)
        self.assertIn("of anders het attribuut `forecast`", self.readme)


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
