"""De berichten naar de Ampwise-portal, zonder Home Assistant-code zodat ze los te testen zijn.

Wat er verstuurd wordt:
- catalog: bij het opstarten en daarna eens per dag een lijst van de sensoren die over ENERGIE gaan (zie is_energy_relevant) met alleen entity_id, device_class, eenheid en naam - NOOIT een
  stand. De portal gebruikt die voor de keuzelijst in Instellingen. Alle andere sensoren verlaten Home Assistant niet.
- entities: de standen (met HA last_updated) van alleen de sensoren die in de portal gekoppeld zijn. Welke dat zijn, zegt de portal in het antwoord op elke push (mapped); wat de klant koppelt
  komt altijd door.
Een portal die dat antwoord (nog) niet kent, of een antwoord dat we niet kunnen lezen (een tunnel die een foutpagina teruggeeft), geeft geen mapped: dan valt de integratie terug op de
energiesensoren (niet meer op alle sensoren), zodat een nieuwe integratie bij een oude portal blijft werken zonder dat er iets meegaat dat niet over energie gaat.

De twee lijsten hieronder zijn dezelfde als in de portal en staan op de privacypagina; pas ze altijd samen aan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


ENERGY_DEVICE_CLASSES = ("power", "energy", "battery", "voltage", "current", "monetary", "gas")
# Vermogen (W, kW), energie (Wh, kWh, MWh), een percentage (batterijstand) en de prijs van stroom. "EUR/kWh" naast "€/kWh" (en "EUR/MWh" naast "€/MWh"): Home Assistant en de prijsintegraties
# schrijven de eenheid van een stroomprijs allebei zo; "ct/kWh" is een prijs in centen. Gas: het type gas telt in elke eenheid (ook gas in kWh, dat ook door de eenheid kWh komt), en de eenheid
# kubieke meters in beide schrijfwijzen ("m³" met superscript-drie en "m3") telt ook zonder type.
ENERGY_UNITS = ("W", "kW", "Wh", "kWh", "MWh", "%", "€/kWh", "EUR/kWh", "ct/kWh", "€/MWh", "EUR/MWh", "m³", "m3")


# Alleen de witruimte van ASCII valt weg rond een waarde, zoals in de portal; str.strip() zonder argument haalt ook een vaste spatie weg.
_ASCII_WHITESPACE = " \t\n\v\f\r"


def is_energy_relevant(device_class: Any, unit: Any) -> bool:
    """Gaat deze sensor over energie? Het type (device_class) of de eenheid moet in de lijst staan; een sensor zonder beide telt niet."""
    dc = str(device_class).strip(_ASCII_WHITESPACE) if device_class else ""
    un = str(unit).strip(_ASCII_WHITESPACE) if unit else ""
    return dc in ENERGY_DEVICE_CLASSES or un in ENERGY_UNITS


def _energy(state: Any) -> bool:
    return is_energy_relevant(state.attributes.get("device_class"), state.attributes.get("unit_of_measurement"))


def _iso(value: Any) -> str | None:
    """HA last_updated als ISO-tekst, of None als er niets bruikbaars is."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return None


def _is_wanted(state: Any, prefix: str) -> bool:
    return str(state.entity_id).startswith(prefix)


def build_catalog(states: Iterable[Any], prefix: str) -> list[dict[str, Any]]:
    """De lijst van energiesensoren zonder standen: entity_id, device_class, eenheid en naam."""
    return [
        {
            "entityId": s.entity_id,
            "unitOfMeasurement": s.attributes.get("unit_of_measurement"),
            "deviceClass": s.attributes.get("device_class"),
            "friendlyName": s.attributes.get("friendly_name"),
        }
        for s in states
        if _is_wanted(s, prefix) and _energy(s)
    ]


def build_states(states: Iterable[Any], mapped: set[str] | None, prefix: str) -> list[dict[str, Any]]:
    """De standen van de gekoppelde sensoren. mapped=None (de portal heeft nog geen lijst gegeven of kent hem niet, of het antwoord was onleesbaar) = alleen de energiesensoren."""
    return [
        {
            "entityId": s.entity_id,
            "state": s.state,
            "unitOfMeasurement": s.attributes.get("unit_of_measurement"),
            "deviceClass": s.attributes.get("device_class"),
            "friendlyName": s.attributes.get("friendly_name"),
            "lastUpdated": _iso(getattr(s, "last_updated", None)),
        }
        for s in states
        if _is_wanted(s, prefix) and ((s.entity_id in mapped) if mapped is not None else _energy(s))
    ]


def update_mapped(previous: set[str] | None, previous_legacy: bool, response: Any) -> tuple[set[str] | None, bool]:
    """Wat de integratie na een antwoord van de portal weet: (de lijst van gekoppelde sensoren of None, of de portal een oudere is die geen lijst kent).

    Alleen een antwoord dat WEL leesbaar is maar GEEN lijst heeft (JSON zonder mapped) is een oudere portal. Een antwoord dat niet te lezen is (een foutpagina van een proxy of een tunnel, geen
    JSON) zegt niets over de portal: wat we wisten blijft gelden, en wist de lijst dus niet (anders zou één foutpagina ertoe leiden dat er opeens alle energiesensoren worden verstuurd)."""
    parsed = parse_mapped(response)
    if parsed is not None:
        return parsed, False
    if isinstance(response, dict):
        return None, True
    return previous, previous_legacy


def states_to_send(states: Iterable[Any], mapped: set[str] | None, legacy_portal: bool, prefix: str) -> list[dict[str, Any]]:
    """De standen voor deze push. Is de lijst van gekoppelde sensoren bekend: alleen die. Is de portal een oudere zonder lijst: de energiesensoren (zoals voorheen, maar niets wat niet over energie
    gaat). Weten we nog niets (het eerste antwoord is er niet of niet te lezen): niets, tot de portal heeft gezegd wat hij wil."""
    if mapped is not None:
        return build_states(states, mapped, prefix)
    if legacy_portal:
        return build_states(states, None, prefix)
    return []


def parse_mapped(response: Any) -> set[str] | None:
    """De lijst van gekoppelde entity-id's uit het antwoord van de portal, of None als het antwoord er geen heeft (een oudere portal)."""
    if not isinstance(response, dict):
        return None
    mapped = response.get("mapped")
    if not isinstance(mapped, list):
        return None
    return {m for m in mapped if isinstance(m, str)}


# --- de prijsfeed (integratie 1.2.0) ---------------------------------------------------------------------------------------------------------------------------------------------------
# De portal zegt in zijn antwoord op elke push welke sensor de prijssensor is (priceEntity). De integratie leest daarvan de attributen raw_today en raw_tomorrow (elk een lijst van {start, end, value}: de
# prijs per kwartier van vandaag en van morgen, de laatste vanaf ongeveer 14:00; het formaat van de Nord Pool-integratie) of, als die er niet zijn of niets bruikbaars bevatten, het attribuut forecast (het
# formaat van de Zonneplan-integratie, zie hieronder) en stuurt ze in de push mee als priceForecast:
#   {"entityId": "sensor.<prijssensor>", "unitOfMeasurement": "EUR/kWh", "attributes": "raw_today+raw_tomorrow", "slots": [{"start": "2026-11-13T00:00:00+01:00", "value": 0.429}, ...]}
# Alleen als de portal een priceEntity noemt (een oudere portal kent het veld niet, en de portal noemt hem alleen voor een account waarvoor hij de lijst wil hebben: anders gaat er niets extra mee), alleen
# van die ene sensor, en niet bij elke push: bij de eerste keer, bij een verandering van de inhoud (hooguit eens per PRICE_FEED_MIN_INTERVAL_SECONDS) en anders hooguit eens per PRICE_FEED_RESEND_SECONDS (const.py).

# De attributen waaruit de prijslijst komt, in de volgorde waarin ze in de feed staan.
PRICE_ATTRIBUTES = ("raw_today", "raw_tomorrow")
# Het formaat van de Zonneplan-integratie: het attribuut forecast, een lijst van items als
#   {"start_date": "2026-11-14T07:45:00+01:00", "end_date": "2026-11-14T08:00:00+01:00", "price_tax_included": {"amount": 4085419}, "price_tax_excluded": {"amount": 2976938}, "sustainability_score": {...}}
# met start_date en end_date als ISO-tekst met verschuiving of als datetime. amount is een geheel getal in 1e-7 euro per kWh (4085419 is 0,4085419 euro/kWh) en is gelijk aan de stand van de sensor: alleen
# price_tax_included gaat mee, nooit price_tax_excluded (de portal legt de stand van de sensor naast de prijs van het lopende kwartier). De waarden zijn dus altijd euro per kWh, ongeacht de eenheid
# die de sensor noemt: is die eenheid iets anders dan euro per kWh dan gaat er niets mee. Een lijst die niet uit aaneengesloten kwartieren van 15 minuten bestaat (de gassensor van dezelfde integratie
# heeft een forecast met een enkel item van 24 uur) wordt NOOIT gestuurd; een item dat niet te lezen is wordt overgeslagen, zoals bij raw_today (ontstaat daardoor een gat, dan gaat de hele lijst niet mee).
PRICE_FORECAST_ATTRIBUTE = "forecast"
PRICE_FORECAST_AMOUNT_SCALE = 10_000_000  # amount is in 1e-7 euro per kWh
# Het bereik van de portal voor een prijs (-1 tot en met 5 euro per kWh): een bedrag daarbuiten is geen prijs, en de portal zou de HELE lijst weigeren, dus dat item wordt overgeslagen.
PRICE_FORECAST_AMOUNT_MIN = -1 * PRICE_FORECAST_AMOUNT_SCALE
PRICE_FORECAST_AMOUNT_MAX = 5 * PRICE_FORECAST_AMOUNT_SCALE
PRICE_QUARTER = timedelta(minutes=15)
# De eenheid die de portal voor een prijs per kWh in euro kent; "€/kWh" (zo schrijft Home Assistant hem) wordt hiertoe omgezet, alleen die.
PRICE_UNIT_EUR_PER_KWH = "EUR/kWh"
PRICE_UNIT_EURO_SIGN = "€/kWh"
# De lengtegrenzen van de portal voor de entity-id en de eenheid in de prijslijst: een langere waarde is geen prijslijst die de portal bewaart, dus dan sturen we hem niet.
PRICE_FEED_MAX_ENTITY_ID_LENGTH = 255
PRICE_FEED_MAX_UNIT_LENGTH = 64
# Een tekst die als begintijd wordt gelezen is hooguit zo lang (ook de lengtegrens van de portal): een langere tekst is geen tijd en wordt niet eens ontleed, zodat een enorme tekst in een attribuut de
# gebeurtenissenlus van Home Assistant niet ophoudt.
PRICE_FEED_MAX_START_LENGTH = 64
# Een lijst met minder slots weigert de portal altijd (met een slot is de afstand tussen de kwartieren niet te zien).
PRICE_FEED_MIN_SLOTS = 2
# Hooguit zoveel items worden BEKEKEN, zoveel keer max_slots (ook de overgeslagen items tellen): een attribuut met miljoenen items of vol rommel houdt de push niet op. Een gewone lijst heeft er 96 per attribuut.
PRICE_FEED_SCAN_FACTOR = 2


def parse_price_entity(response: Any) -> str | None:
    """De prijssensor die de portal in zijn antwoord noemt (priceEntity), of None: geen leesbaar antwoord, een oudere portal zonder het veld, null, een lege tekst of iets dat geen tekst is."""
    if not isinstance(response, dict):
        return None
    entity = response.get("priceEntity")
    if isinstance(entity, str) and entity:
        return entity
    return None


def update_price_entity(previous: str | None, response: Any) -> str | None:
    """De prijssensor na een antwoord van de portal. Een leesbaar antwoord is leidend (ook null en een oudere portal zonder het veld: geen prijssensor); een onleesbaar antwoord (een foutpagina van
    een proxy of een tunnel, geen JSON) zegt niets over de portal en laat staan wat we wisten, zoals update_mapped."""
    if isinstance(response, dict):
        return parse_price_entity(response)
    return previous


def _price_moment(value: Any) -> datetime | None:
    """Een tijd als datetime MET verschuiving, of None. Een datetime heeft die verschuiving (HA geeft datetime-objecten); een tekst wordt gelezen. Een tijd zonder verschuiving is onbruikbaar (de portal
    weet de tijdzone niet) en telt als onleesbaar. Een tekst van meer dan PRICE_FEED_MAX_START_LENGTH tekens is onleesbaar, zonder dat hij wordt ontleed."""
    if isinstance(value, str):
        if len(value) > PRICE_FEED_MAX_START_LENGTH:
            return None
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _price_start(value: Any) -> str | None:
    """De begintijd van een kwartier als ISO-tekst MET verschuiving, of None (zie _price_moment). Een tekst wordt opnieuw opgemaakt zodat de portal altijd hetzelfde formaat krijgt."""
    moment = _price_moment(value)
    return None if moment is None else moment.isoformat()


def _utc(moment: datetime) -> datetime | None:
    """Dezelfde tijd in UTC, of None als dat niet kan (een jaartal buiten het bereik). Tijden worden altijd in UTC vergeleken: met dezelfde tijdzone aan beide kanten rekent Python met de wandtijd, en dat
    gaat mis op de dag dat de klok verspringt (02:45 +02:00 en 02:00 +01:00 liggen een kwartier uit elkaar, niet drie kwartier terug)."""
    try:
        return moment.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _start_fits_portal(moment: datetime | None) -> bool:
    """Leest de portal deze begintijd? Hij eist een tijd met een UTC-verschil in hele minuten (+01:00) die in UTC op een kwartiergrens ligt, zonder seconden of een deel van een seconde. Een andere begintijd
    laat de portal de HELE lijst weigeren."""
    if moment is None:
        return False
    offset = moment.utcoffset()
    if offset is None or offset % timedelta(minutes=1):
        return False
    utc = _utc(moment)
    return utc is not None and utc.minute % 15 == 0 and utc.second == 0 and utc.microsecond == 0


def _slots_fit_portal(slots: list[dict[str, Any]]) -> bool:
    """Zou de portal deze lijst aannemen, voor zover dat aan de lijst zelf te zien is? Minstens PRICE_FEED_MIN_SLOTS slots, en elke begintijd (zoals hij verstuurd wordt) op een kwartiergrens in UTC (zie
    _start_fits_portal). Een lijst die de portal altijd weigert gaat niet mee: elke weigering telt voor de bewaking van de prijslijst in de portal."""
    return len(slots) >= PRICE_FEED_MIN_SLOTS and all(_start_fits_portal(_price_moment(slot["start"])) for slot in slots)


def _price_unit(unit: str | None) -> str | None:
    """De eenheid zoals de integratie hem stuurt: "€/kWh" wordt "EUR/kWh" (zo schrijft de portal hem, en zo hoeft hij alleen die ene naam te kennen), al het andere blijft zoals het is."""
    return PRICE_UNIT_EUR_PER_KWH if unit == PRICE_UNIT_EURO_SIGN else unit


def _price_amount(value: Any) -> float | None:
    """Een bedrag van de Zonneplan-integratie (een geheel getal in 1e-7 euro per kWh) als euro per kWh, of None. Alleen een geheel getal (int, of een float zonder breuk: 4085419.0; geen True/False, geen tekst,
    geen None, geen NaN of oneindig, geen 4085419.5) binnen het bereik van de portal (-1 tot en met 5 euro per kWh): ook een geheel getal dat niet in een float past (10**400) is dus geen prijs, nooit een fout."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, float):
            if not value.is_integer():  # ook NaN en oneindig
                return None
            value = int(value)
        if not isinstance(value, int) or not PRICE_FORECAST_AMOUNT_MIN <= value <= PRICE_FORECAST_AMOUNT_MAX:
            return None
        return value / PRICE_FORECAST_AMOUNT_SCALE
    except Exception:  # noqa: BLE001 - een vreemd getaltype dat bij vergelijken of delen een fout gooit is geen prijs
        return None


def _forecast_slots(items: Iterable[Any], max_slots: int) -> list[dict[str, Any]]:
    """De slots uit een forecast-lijst van de Zonneplan-integratie ([] = niets te sturen). Een item zonder leesbare start_date of end_date of zonder leesbaar price_tax_included.amount wordt overgeslagen;
    een item dat geen kwartier van 15 minuten duurt (end_date min start_date) maakt de HELE lijst onbruikbaar (dat is de gasvorm met een item van 24 uur, of een uurreeks: nooit als kwartierlijst lezen), en
    ook een gat, een overlap of een terugsprong tussen twee leesbare items (de portal weigert zo'n lijst helemaal en rekent hem dan mee voor zijn uurlijkse grens). Hooguit max_slots slots."""
    slots: list[dict[str, Any]] = []
    previous_start: datetime | None = None
    for item in items:
        if len(slots) >= max_slots:
            break
        if not hasattr(item, "get"):
            continue
        start = _price_moment(item.get("start_date"))
        end = _price_moment(item.get("end_date"))
        start_utc = _utc(start) if start is not None else None
        end_utc = _utc(end) if end is not None else None
        if start_utc is None or end_utc is None:
            continue
        if end_utc - start_utc != PRICE_QUARTER:
            return []
        included = item.get("price_tax_included")
        value = _price_amount(included.get("amount")) if hasattr(included, "get") else None
        if value is None:
            continue
        if previous_start is not None and start_utc - previous_start != PRICE_QUARTER:
            return []
        slots.append({"start": start.isoformat(), "value": value})
        previous_start = start_utc
    return slots


def _price_value(value: Any) -> float | None:
    """De prijs als getal, of None: alleen een echt getal (geen tekst, geen True/False) en nooit NaN of oneindig (dat is geen geldige JSON en liet de portal de hele push weigeren). Een getal dat niet
    in een float past (een geheel getal boven 1e308 geeft OverflowError) of waar iets anders mee misgaat is geen prijs: None, nooit een fout (de prijslijst mag de gewone push nooit stoppen)."""
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if number != number or abs(number) == float("inf"):
            return None
        return number
    except Exception:  # noqa: BLE001 - OverflowError en wat een vreemd getaltype ook gooit
        return None


def build_price_forecast(price_state: Any, prefix: str, max_slots: int) -> dict[str, Any] | None:
    """De prijsfeed uit de prijssensor, of None als er niets bruikbaars is (geen sensor, geen sensor.-entiteit, geen van de attributen, geen leesbaar item). De bron wordt per sensor bepaald: heeft hij
    raw_today of raw_tomorrow met leesbare items dan gaan die mee; anders, heeft hij een forecast-lijst van de Zonneplan-integratie (zie PRICE_FORECAST_ATTRIBUTE) dan gaat die mee; anders niets. Een lijst
    die de portal altijd weigert (minder dan PRICE_FEED_MIN_SLOTS slots, of een begintijd die niet op een kwartiergrens in UTC ligt, zie _slots_fit_portal) is geen bruikbare lijst: bij raw_today en
    raw_tomorrow is dat een reden om het attribuut forecast te proberen, bij forecast om niets te sturen.
    Een item zonder leesbare start of zonder getal wordt overgeslagen; hooguit max_slots items (de eerste, in de volgorde van de sensor) en hooguit PRICE_FEED_SCAN_FACTOR keer zoveel items bekeken (over alle
    attributen samen), overgeslagen items meegeteld."""
    if price_state is None or not _is_wanted(price_state, prefix):
        return None
    entity_id = str(price_state.entity_id)
    if len(entity_id) > PRICE_FEED_MAX_ENTITY_ID_LENGTH:
        return None
    unit = price_state.attributes.get("unit_of_measurement")
    if unit is not None and (not isinstance(unit, str) or len(unit) > PRICE_FEED_MAX_UNIT_LENGTH):
        return None
    unit = _price_unit(unit)
    slots: list[dict[str, Any]] = []
    used: list[str] = []
    viewed = 0
    max_viewed = max_slots * PRICE_FEED_SCAN_FACTOR
    for name in PRICE_ATTRIBUTES:
        items = price_state.attributes.get(name)
        if not isinstance(items, (list, tuple)):
            continue
        before = len(slots)
        # een plak van hooguit het nog resterende aantal te bekijken items: een lijst met miljoenen items wordt niet doorlopen (en ook niet gekopieerd)
        for item in items[: max(max_viewed - viewed, 0)]:
            if len(slots) >= max_slots:
                break
            viewed += 1
            if not hasattr(item, "get"):
                continue
            start = _price_start(item.get("start"))
            value = _price_value(item.get("value"))
            if start is None or value is None:
                continue
            slots.append({"start": start, "value": value})
        if len(slots) > before:
            used.append(name)
    if _slots_fit_portal(slots):
        return {"entityId": entity_id, "unitOfMeasurement": unit, "attributes": "+".join(used), "slots": slots}
    # geen leesbare raw_today of raw_tomorrow (of een lijst die de portal altijd weigert): het formaat van de Zonneplan-integratie. De waarden zijn daar euro per kWh, dus de eenheid van de sensor moet dat zijn
    # (of ontbreken).
    forecast = price_state.attributes.get(PRICE_FORECAST_ATTRIBUTE)
    if isinstance(forecast, (list, tuple)) and unit in (None, PRICE_UNIT_EUR_PER_KWH):
        slots = _forecast_slots(forecast[: max(max_viewed - viewed, 0)], max_slots)
        if _slots_fit_portal(slots):
            return {"entityId": entity_id, "unitOfMeasurement": PRICE_UNIT_EUR_PER_KWH, "attributes": PRICE_FORECAST_ATTRIBUTE, "slots": slots}
    return None


def price_forecast_signature(forecast: dict[str, Any] | None) -> str | None:
    """Een handtekening van de inhoud van de feed (de sensor, de eenheid en elk slot met zijn volle precisie): dezelfde inhoud geeft dezelfde tekst, elke andere waarde, begintijd of aantal een andere.
    None zonder feed. Een tekst in plaats van een hash: de vergelijking is exact en de integratie heeft geen extra modules nodig."""
    if not forecast:
        return None
    head = f"{forecast['entityId']}|{forecast['unitOfMeasurement']}|{forecast['attributes']}"
    return head + "#" + ";".join(f"{slot['start']}={slot['value']!r}" for slot in forecast["slots"])


def should_send_price_forecast(
    signature: str | None,
    last_signature: str | None,
    last_sent_at: float | None,
    now: float,
    resend_seconds: float,
    min_interval_seconds: float,
) -> bool:
    """Gaat de feed in deze push mee? Alleen met een feed, en dan: de eerste keer (nog nooit iets verstuurd), bij een andere inhoud dan de laatst verstuurde maar niet eerder dan min_interval_seconds na
    die laatste (een sensor waarvan de attributen bij elke tick veranderen stuurt zo hooguit eens per min_interval_seconds en niet elke 5 tot 30 seconden 10 tot 20 kB), of als de laatste keer
    resend_seconds of langer geleden is (zodat een gemiste push geen gat laat). Niet bij elke push van 5 of 30 seconden. `now` en `last_sent_at` zijn tijden van een monotone klok (seconden)."""
    if signature is None:
        return False
    if last_sent_at is None:
        return True
    elapsed = now - last_sent_at
    if last_signature != signature:
        return elapsed >= min_interval_seconds
    return elapsed >= resend_seconds


def price_retry_delay(failures: int, base_seconds: float, max_seconds: float) -> float:
    """Hoe lang een lijst die niet is aangekomen wacht voor de volgende poging: base_seconds na de eerste mislukking, daarna steeds het dubbele, nooit meer dan max_seconds. Zo valt een lijst die steeds
    mislukt (de portal verwerkt hem wel, maar het antwoord komt niet aan) niet elke tick opnieuw lastig en eet hij de lijsten per uur van de portal niet op."""
    return min(base_seconds * (2 ** (min(max(failures, 1), 30) - 1)), max_seconds)


def price_forecast_to_send(
    get_state: Any,
    price_entity: str | None,
    prefix: str,
    max_slots: int,
    last_signature: str | None,
    last_sent_at: float | None,
    now: float,
    resend_seconds: float,
    min_interval_seconds: float,
    retry_not_before: float | None = None,
    on_error: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """(de feed, zijn handtekening) voor deze push, of (None, None) als er niets bij hoort. Zonder priceEntity (een oudere portal, of de portal heeft geen prijssensor) altijd (None, None): de push is dan
    precies die van 1.1.0. `get_state` geeft de huidige toestand van een sensor in Home Assistant (hass.states.get; None als hij niet bestaat). De aanroeper bewaart de handtekening en de tijd pas als de
    push gelukt is; `retry_not_before` is het moment (monotone klok) waarvoor na een niet aangekomen lijst geen nieuwe lijst gaat. De prijslijst mag de gewone push NOOIT stoppen: elke fout in dit hele deel (de toestand lezen, de lijst bouwen, de handtekening) geeft (None, None), dus een push zonder prijslijst;
    `on_error(fout)`, als er een is, mag dat melden (en gooit zelf nooit door)."""
    if not price_entity:
        return None, None
    if retry_not_before is not None and now < retry_not_before:
        return None, None  # de laatste lijst is niet aangekomen: nog even wachten (zie price_retry_delay)
    try:
        forecast = build_price_forecast(get_state(price_entity), prefix, max_slots)
        signature = price_forecast_signature(forecast)
        if not should_send_price_forecast(signature, last_signature, last_sent_at, now, resend_seconds, min_interval_seconds):
            return None, None
        return forecast, signature
    except Exception as err:  # noqa: BLE001 - zie de docstring: terugval op "geen prijslijst"
        if on_error is not None:
            try:
                on_error(err)
            except Exception:  # noqa: BLE001 - ook het melden mag de push niet stoppen
                pass
        return None, None
