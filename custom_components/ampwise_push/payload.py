"""De berichten naar de Ampwise-portal, zonder Home Assistant-code zodat ze los te testen zijn.

Wat er verstuurd wordt:
- catalog: bij het opstarten en daarna eens per dag een lijst van de sensoren die over ENERGIE gaan (zie is_energy_relevant) met alleen entity_id, device_class, eenheid en naam - NOOIT een
  stand. De portal gebruikt die voor de keuzelijst in Instellingen. Alle andere sensoren verlaten Home Assistant niet.
- entities: de standen (met HA last_updated) van alleen de sensoren die in de portal gekoppeld zijn. Welke dat zijn, zegt de portal in het antwoord op elke push (mapped); wat de klant koppelt
  komt altijd door.
Een portal die dat antwoord (nog) niet kent, of een antwoord dat we niet kunnen lezen (een tunnel die een foutpagina teruggeeft), geeft geen mapped: dan valt de integratie terug op de
energiesensoren (niet meer op alle sensoren), zodat een nieuwe integratie bij een oude portal blijft werken zonder dat er iets meegaat dat niet over energie gaat.

De twee lijsten hieronder zijn dezelfde als in de portal (src/lib/energyRelevance.ts) en staan op de privacypagina; pas ze altijd samen aan.
"""
from __future__ import annotations

from typing import Any, Iterable


ENERGY_DEVICE_CLASSES = ("power", "energy", "battery", "voltage", "current", "monetary")
# "EUR/kWh" naast "€/kWh": Home Assistant en de prijsintegraties schrijven de eenheid van een stroomprijs allebei zo.
ENERGY_UNITS = ("W", "kWh", "%", "€/kWh", "EUR/kWh")


# Alleen de witruimte van ASCII valt weg rond een waarde, zoals in de portal (src/lib/energyRelevance.ts); str.strip() zonder argument haalt ook een vaste spatie weg.
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
