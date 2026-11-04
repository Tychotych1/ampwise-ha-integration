# Ampwise voor Home Assistant

Stuurt de standen van de sensoren die je in de Ampwise-portal koppelt naar de portal. De integratie maakt zelf geen entiteiten aan en stuurt niets terug naar je huis.

## Installeren

1. HACS openen, Integraties, de drie puntjes, Aangepaste repository. Plak het adres van deze repository en kies Integratie.
2. Ampwise installeren en Home Assistant herstarten.
3. Instellingen, Apparaten en diensten, Integratie toevoegen, Ampwise. Plak de API-sleutel uit de portal (Instellingen, Home Assistant-integratie) en laat het adres en het interval staan. Het interval is een aantal seconden tussen 5 en 3600 (standaard 30).
4. In de portal koppel je onder Instellingen de sensoren aan je metingen. Binnen een halve minuut stuurt de integratie de standen van precies die sensoren.

## Wat er verstuurd wordt

- Bij het opstarten en daarna eens per dag: een lijst van je sensoren die over energie gaan (vermogen, energie, batterij, spanning, stroom, bedrag, of een eenheid als W, kWh, % of ct/kWh) met alleen naam, type en eenheid. Geen standen. Andere sensoren (temperatuur, aanwezigheid, gas in kubieke meters) staan er niet in en verlaten je Home Assistant niet. De precieze lijst staat op de privacypagina van de portal. De portal gebruikt de lijst voor de keuzelijst in Instellingen.
- Elke 30 seconden (instelbaar): de stand van de sensoren die je in de portal hebt gekoppeld, met het moment waarop Home Assistant de waarde het laatst veranderde, en het versienummer van de integratie.
- De portal zegt in zijn antwoord welke sensoren gekoppeld zijn; alleen van die sensoren gaan standen mee. Een nieuwe integratie bij een oudere portal die dat antwoord niet kent, stuurt de energiesensoren (niet alle sensoren). Zolang er nog geen leesbaar antwoord is geweest, gaan er geen standen mee.
- Is de portal niet bereikbaar, of weigert hij de sleutel (401) of de versie (426), dan komt er een waarschuwing in het logboek van Home Assistant (hooguit een per uur) en probeert de integratie het bij de volgende keer opnieuw. Bij herstel staat er een melding dat de verbinding terug is.

Versies zonder versienummer (1.0.0 en eerder) worden door de portal nog 30 dagen aangenomen en daarna niet meer: werk bij via HACS.

## Testen

- `python -m unittest discover -s tests -t .` draait de tests van de berichten en van de bestanden rond de integratie (tests/test_payload.py en tests/test_metadata.py): geen Home Assistant nodig.
- De tests die de integratie laden zoals Home Assistant dat doet (config flow, setup, pushes, storingen; tests/ha/) gebruiken pytest-homeassistant-custom-component:
  `python -m venv .venv`, daarna `.venv/Scripts/python -m pip install -r requirements_test.txt` (Linux/macOS: `.venv/bin/python`) en `.venv/Scripts/python -m pytest tests`.
  Welke versie van Home Assistant de tests nabootsen staat in requirements_test.txt.
- In GitHub draaien dezelfde tests bij elke pull request en elke push naar main (`.github/workflows/test.yml`), op Linux met Python 3.14 en pytest-homeassistant-custom-component 0.13.375 (Home Assistant 2026.10.4, de versie in productie; `requirements_test_ci.txt`). Lokaal op Python 3.12 bootsen de tests Home Assistant 2025.1.4 na (`requirements_test.txt`): een groene lokale run bewijst dus minder dan de CI.
