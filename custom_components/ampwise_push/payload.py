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


def is_energy_relevant(device_class: Any, unit: Any) -> bool:
    """Gaat deze sensor over energie? Het type (device_class) of de eenheid moet in de lijst staan; een sensor zonder beide telt niet."""
    dc = str(device_class).strip() if device_class else ""
    un = str(unit).strip() if unit else ""
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


def parse_mapped(response: Any) -> set[str] | None:
    """De lijst van gekoppelde entity-id's uit het antwoord van de portal, of None als het antwoord er geen heeft (een oudere portal)."""
    if not isinstance(response, dict):
        return None
    mapped = response.get("mapped")
    if not isinstance(mapped, list):
        return None
    return {m for m in mapped if isinstance(m, str)}
