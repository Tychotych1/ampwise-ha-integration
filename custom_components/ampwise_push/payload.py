"""De berichten naar de Ampwise-portal, zonder Home Assistant-code zodat ze los te testen zijn.

Wat er verstuurd wordt:
- catalog: bij het opstarten en daarna eens per dag een lijst van alle sensoren met alleen entity_id, device_class, eenheid en naam - NOOIT een stand. De portal gebruikt die voor de
  keuzelijst in Instellingen.
- entities: de standen (met HA last_updated) van alleen de sensoren die in de portal gekoppeld zijn. Welke dat zijn, zegt de portal in het antwoord op elke push (mapped).
Een portal die dat antwoord (nog) niet kent, geeft geen mapped terug; dan valt de integratie terug op het oude gedrag (alle sensoren), zodat een nieuwe integratie bij een oude portal blijft werken.
"""
from __future__ import annotations

from typing import Any, Iterable


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
    """De lijst van sensoren zonder standen: entity_id, device_class, eenheid en naam."""
    return [
        {
            "entityId": s.entity_id,
            "unitOfMeasurement": s.attributes.get("unit_of_measurement"),
            "deviceClass": s.attributes.get("device_class"),
            "friendlyName": s.attributes.get("friendly_name"),
        }
        for s in states
        if _is_wanted(s, prefix)
    ]


def build_states(states: Iterable[Any], mapped: set[str] | None, prefix: str) -> list[dict[str, Any]]:
    """De standen van de gekoppelde sensoren. mapped=None (de portal heeft nog geen lijst gegeven of kent hem niet) = alle sensoren, zoals de oude integratie."""
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
        if _is_wanted(s, prefix) and (mapped is None or s.entity_id in mapped)
    ]


def parse_mapped(response: Any) -> set[str] | None:
    """De lijst van gekoppelde entity-id's uit het antwoord van de portal, of None als het antwoord er geen heeft (een oudere portal)."""
    if not isinstance(response, dict):
        return None
    mapped = response.get("mapped")
    if not isinstance(mapped, list):
        return None
    return {m for m in mapped if isinstance(m, str)}
