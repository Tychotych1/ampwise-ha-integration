# Ampwise voor Home Assistant

Stuurt de standen van de sensoren die je in de Ampwise-portal koppelt naar de portal. De integratie maakt zelf geen entiteiten aan en stuurt niets terug naar je huis.

Je hebt Home Assistant 2025.1 of nieuwer nodig en een API-sleutel uit de Ampwise-portal.

## Installeren

1. Voeg deze repository toe:
   - Home Assistant 2026.11 of nieuwer (de Marketplace): Instellingen, Marketplace, en accepteer de waarschuwing. Kies rechtsboven "Add from link", vul `https://github.com/Tychotych1/ampwise-ha-integration` in en kies Add. Heb je GitHub nog niet gekoppeld, dan vraagt de Marketplace daar nu om, zie hieronder.
   - Oudere versies met HACS: HACS openen, Integraties, de drie puntjes, Aangepaste repository. Plak het adres van deze repository en kies Integratie.
2. Ampwise installeren (in de Marketplace: Ampwise openen en Install kiezen) en Home Assistant herstarten als daarom wordt gevraagd.
3. Instellingen, Apparaten en diensten, Integratie toevoegen, Ampwise. Plak de API-sleutel uit de portal (Instellingen, Home Assistant-integratie) en laat het adres en het interval staan. Het interval is een aantal seconden tussen 5 en 3600 (standaard 30).
4. In de portal koppel je onder Instellingen de sensoren aan je metingen. Binnen een halve minuut stuurt de integratie de standen van precies die sensoren.

### GitHub koppelen (Marketplace, Home Assistant 2026.11)

Deze repository staat niet in de catalogus van de Marketplace; je voegt hem toe als eigen repository. Daarvoor heeft de Marketplace een koppeling met GitHub nodig, en dus een GitHub-account (aanmaken is gratis). Zonder die koppeling kun je hem niet toevoegen.

- Home Assistant toont een code en een link naar GitHub. Je opent de link, voert de code in en keurt de koppeling goed op GitHub. Je typt geen wachtwoord in Home Assistant (GitHub "device sign-in").
- Volgens de documentatie van Home Assistant vraagt de koppeling geen toegang tot privérepositories en geen recht om iets op GitHub te wijzigen: de Marketplace kan alleen openbare informatie lezen. Home Assistant bewaart een toegangstoken om de koppeling te onderhouden.
- Je kunt de koppeling altijd intrekken in je GitHub-account, onder Applications, Authorized OAuth Apps.

Zie de documentatie van de Marketplace: https://www.home-assistant.io/integrations/marketplace/.

## Welke gegevens stuurt de integratie?

De integratie leest alleen de standen van sensoren in Home Assistant en stuurt een deel daarvan naar de Ampwise-portal. Hieronder staat precies welk deel.

### Welke sensoren

- Alleen entiteiten van het type sensor (`sensor.…`). Andere entiteiten (schakelaars, lampen, aanwezigheid, enzovoort) worden nooit verstuurd.
- Daarvan alleen sensoren die over energie gaan: een type (device class) power, energy, battery, voltage, current, monetary of gas, of een eenheid W, kW, Wh, kWh, MWh, %, €/kWh, EUR/kWh, ct/kWh, €/MWh, EUR/MWh, m³ of m3.
- Let op: het type battery en de eenheden % en m³ komen ook voor bij sensoren die niet over energie gaan (de batterij van een telefoon, luchtvochtigheid, een watermeter in kubieke meters); die staan er dan wel in. Andere sensoren (temperatuur, aanwezigheid, water in liters) staan er niet in en verlaten je Home Assistant niet. De lijst staat ook op de privacypagina van de portal: https://ampwise.nl/privacy.

### Wat gaat er per sensor mee

- Voor de keuzelijst in de portal, zonder stand: de entity-id, de naam, het type en de eenheid van elke sensor die over energie gaat.
- Voor de metingen, alleen van de sensoren die je in de portal koppelt: dezelfde velden, plus de stand (de waarde, als tekst) en het moment waarop Home Assistant de waarde het laatst veranderde.
- Bij elk bericht: het versienummer van de integratie.
- Geen andere eigenschappen (attributen) van de sensor. De naam is de naam die je in Home Assistant aan de sensor gaf; staat daar een persoonlijk woord in, dan gaat dat mee.

### Hoe vaak

- Bij het opstarten en daarna elke 24 uur: de lijst van je energiesensoren, zonder standen.
- Elke 30 seconden (instelbaar van 5 tot 3600): de standen van de gekoppelde sensoren. Is er niets gekoppeld, dan gaat er toch een bericht zonder standen, zodat de portal ziet dat de integratie leeft.
- Bij het koppelen test de integratie de sleutel één keer met een bericht zonder standen.
- De portal zegt in zijn antwoord welke sensoren gekoppeld zijn; alleen van die sensoren gaan standen mee. Een nieuwe integratie bij een oudere portal die dat antwoord niet kent, stuurt de energiesensoren (niet alle sensoren). Zolang er nog geen leesbaar antwoord is geweest, gaan er geen standen mee.

### Waarheen en hoe beveiligd

- De berichten gaan naar `https://ampwise.nl/api/ingest`. Dat is de standaardwaarde in het formulier.
- Het adres begint met https, dus de verbinding is versleuteld. Het adres is in het formulier aan te passen en de integratie dwingt https niet af: laat het adres staan, of gebruik alleen een adres dat met https begint.
- De API-sleutel uit de portal gaat mee in de Authorization-header van elk bericht. De sleutel staat in de configuratie van de integratie in Home Assistant.

### Wat niet wordt verstuurd

- Sensoren die niet over energie gaan, en alle andere soorten entiteiten.
- Van een sensor niets anders dan de velden hierboven: geen attributen, geen apparaat of ruimte, geen geschiedenis.
- Niets over jou of je huis zelf: geen locatie, geen gebruikers, geen netwerkinstellingen, geen logboek. De integratie leest alleen de standen van de sensoren.

### Storingen

Is de portal niet bereikbaar, of weigert hij de sleutel (401) of de versie (426), dan komt er een waarschuwing in het logboek van Home Assistant (hooguit een per uur) en probeert de integratie het bij de volgende keer opnieuw. Bij herstel staat er een melding dat de verbinding terug is.

Versies zonder versienummer (1.0.0 en eerder) worden door de portal nog 30 dagen aangenomen en daarna niet meer: werk bij via de Marketplace of HACS.

### Stoppen en verwijderen

- Verwijder Ampwise onder Instellingen, Apparaten en diensten. Home Assistant stuurt dan niets meer. Wil je ook de bestanden weg: verwijder Ampwise daarna in de Marketplace (drie puntjes, Uninstall) of in HACS.
- Trek de sleutel in bij de portal: Instellingen, Home Assistant-integratie, Sleutel intrekken. De portal neemt dan niets meer aan met die sleutel. Wat de portal bewaart en hoe je je gegevens laat wissen staat op https://ampwise.nl/privacy.

## Testen

- `python -m unittest discover -s tests -t .` draait de tests van de berichten en van de bestanden rond de integratie (tests/test_payload.py en tests/test_metadata.py): geen Home Assistant nodig.
- De tests die de integratie laden zoals Home Assistant dat doet (config flow, setup, pushes, storingen; tests/ha/) gebruiken pytest-homeassistant-custom-component:
  `python -m venv .venv`, daarna `.venv/Scripts/python -m pip install -r requirements_test.txt` (Linux/macOS: `.venv/bin/python`) en `.venv/Scripts/python -m pytest tests`.
  Welke versie van Home Assistant de tests nabootsen staat in requirements_test.txt.
- In GitHub draaien dezelfde tests bij elke pull request en elke push naar main (`.github/workflows/test.yml`), op Linux met Python 3.14 en pytest-homeassistant-custom-component 0.13.375 (Home Assistant 2026.10.4, de versie in productie; `requirements_test_ci.txt`). Lokaal op Python 3.12 bootsen de tests Home Assistant 2025.1.4 na (`requirements_test.txt`): een groene lokale run bewijst dus minder dan de CI.
- Daarnaast draaien hassfest (de controle van Home Assistant op een integratie) en de HACS-controle bij elke pull request, elke push naar main en elke week (`.github/workflows/validate.yml`).

## Licentie en merk

De code staat onder de MIT-licentie (zie `LICENSE`): je mag hem gebruiken, aanpassen en delen. De licentie geldt alleen voor de code. De naam en het merk "Ampwise" en het logo vallen er niet onder; die blijven van de eigenaar van Ampwise. Je mag ze niet gebruiken als naam van je eigen product of bedrijf. Dat geldt ook voor de bestanden in `custom_components/ampwise_push/brand/` (het logo): die staan in deze repository zodat Home Assistant en HACS het icoon kunnen tonen, maar ze vallen niet onder de MIT-licentie. Een kopie of aanpassing van deze code krijgt dus een eigen naam en een eigen logo.
