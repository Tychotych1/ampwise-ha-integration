# Ampwise voor Home Assistant

Stuurt de standen van de sensoren die je in de Ampwise-portal koppelt naar de portal. De integratie maakt zelf geen entiteiten aan en stuurt niets terug naar je huis.

## Installeren

1. HACS openen, Integraties, de drie puntjes, Aangepaste repository. Plak het adres van deze repository en kies Integratie.
2. Ampwise installeren en Home Assistant herstarten.
3. Instellingen, Apparaten en diensten, Integratie toevoegen, Ampwise. Plak de API-sleutel uit de portal (Instellingen, Home Assistant-integratie) en laat het adres en het interval staan.
4. In de portal koppel je onder Instellingen de sensoren aan je metingen. Binnen een halve minuut stuurt de integratie de standen van precies die sensoren.

## Wat er verstuurd wordt

- Bij het opstarten en daarna eens per dag: een lijst van al je sensoren met alleen naam, type en eenheid. Geen standen. De portal gebruikt die voor de keuzelijst.
- Elke 30 seconden (instelbaar): de stand van de sensoren die je in de portal hebt gekoppeld, met het moment waarop Home Assistant de waarde het laatst veranderde, en het versienummer van de integratie.
- De portal zegt in zijn antwoord welke sensoren gekoppeld zijn; alleen van die sensoren gaan standen mee. Een nieuwe integratie bij een oudere portal die dat antwoord niet kent, stuurt alle sensoren, zoals de versie ervoor.

Versies zonder versienummer (1.0.0 en eerder) worden door de portal nog 30 dagen aangenomen en daarna niet meer: werk bij via HACS.

## Testen

`python -m unittest discover -s tests -t .` draait de tests van de berichten (geen Home Assistant nodig).
