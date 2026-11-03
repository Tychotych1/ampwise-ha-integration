"""Ampwise push-integratie.

Stuurt de standen van de sensoren die in de Ampwise-portal gekoppeld zijn naar de portal (cloud_push) - geen platform, geen entities die deze integratie zelf aanmaakt, alleen een
achtergrondtaak die bestaande states doorstuurt. Zie geen coordinator.py: HA's DataUpdateCoordinator is voor het ophalen van data IN Home Assistant op een schema, niet voor het naar
buiten sturen ervan - dat patroon past hier dus niet.

Bij het opstarten en daarna eens per dag gaat er ook een lijst van alle sensoren (naam, type, eenheid, zonder stand) naar de portal voor de keuzelijst; zie payload.py.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CATALOG_INTERVAL,
    CONF_API_KEY,
    CONF_INGEST_URL,
    CONF_PUSH_INTERVAL,
    DOMAIN,
    ENTITY_DOMAIN_PREFIX,
    INTEGRATION_VERSION,
    LOG_COOLDOWN_SECONDS,
    REQUEST_TIMEOUT,
)
from .payload import build_catalog, build_states, parse_mapped

_LOGGER = logging.getLogger(__name__)


class _PushState:
    """Houdt bij of we in storing zitten (zodat we niet elke tick loggen) en welke sensoren de portal wil hebben."""

    def __init__(self) -> None:
        self.failing = False
        self.last_logged = 0.0
        # De entity-id's waarvan de portal de standen wil; None = nog niet bekend (of de portal kent de lijst niet: dan sturen we alles, zoals voorheen).
        self.mapped: set[str] | None = None
        self.catalog_sent = False
        self.legacy_portal = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api_key = entry.data[CONF_API_KEY]
    ingest_url = entry.data[CONF_INGEST_URL]
    interval = entry.data[CONF_PUSH_INTERVAL]
    session = async_get_clientsession(hass)
    state = _PushState()

    def _log_failure(message: str, *args: Any) -> None:
        now = time.monotonic()
        if not state.failing or now - state.last_logged > LOG_COOLDOWN_SECONDS:
            _LOGGER.warning(message, *args)
            state.last_logged = now
        state.failing = True

    async def _post(body: dict[str, Any]) -> Any:
        """Eén POST naar de portal; geeft het antwoord (JSON) terug of gooit bij een fout."""
        async with session.post(
            ingest_url,
            json={"version": INTEGRATION_VERSION, **body},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status == 426:
                raise aiohttp.ClientError("de portal accepteert deze versie van de integratie niet meer - werk hem bij via HACS")
            if resp.status != 200:
                raise aiohttp.ClientError(f"HTTP {resp.status}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return None

    def _handle_response(response: Any) -> None:
        mapped = parse_mapped(response)
        if mapped is None:
            # Een oudere portal zonder lijst van gekoppelde sensoren: alles blijven sturen.
            state.legacy_portal = True
            state.mapped = None
        else:
            state.legacy_portal = False
            state.mapped = mapped

    async def _send_catalog(_now: Any = None) -> None:
        # hass.states.async_all() is synchroon, geen await nodig/mogelijk.
        catalog = build_catalog(hass.states.async_all(), ENTITY_DOMAIN_PREFIX)
        try:
            _handle_response(await _post({"catalog": catalog, "entities": []}))
            state.catalog_sent = True
            if state.failing:
                _LOGGER.warning("Ampwise: verbinding hersteld, data wordt weer verstuurd.")
            state.failing = False
        except (aiohttp.ClientError, TimeoutError) as err:
            _log_failure("Ampwise: kon de lijst met sensoren niet versturen (%s), probeer het later opnieuw.", err)

    async def _push(_now: Any) -> None:
        # Nog geen lijst gestuurd (de portal was bij het opstarten niet bereikbaar): eerst die, het antwoord zegt welke sensoren de portal wil.
        if not state.catalog_sent:
            await _send_catalog()
            if not state.catalog_sent:
                return

        entities = build_states(hass.states.async_all(), state.mapped, ENTITY_DOMAIN_PREFIX)
        try:
            # Ook zonder standen (niets gekoppeld) een bericht: de portal ziet zo dat de integratie leeft en welke versie hij heeft, en het antwoord ververst de lijst van gekoppelde sensoren.
            _handle_response(await _post({"entities": entities}))
            if state.failing:
                _LOGGER.warning("Ampwise: verbinding hersteld, data wordt weer verstuurd.")
            state.failing = False
        except (aiohttp.ClientError, TimeoutError) as err:
            _log_failure("Ampwise: kon data niet versturen (%s), probeer het later opnieuw.", err)

    hass.async_create_task(_send_catalog())
    unsub_push = async_track_time_interval(hass, _push, timedelta(seconds=interval))
    unsub_catalog = async_track_time_interval(hass, _send_catalog, CATALOG_INTERVAL)

    def _unsub() -> None:
        unsub_push()
        unsub_catalog()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _unsub
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unsub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if unsub:
        unsub()
    return True
