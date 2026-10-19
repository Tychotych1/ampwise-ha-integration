"""Ampwise push-integratie.

Stuurt periodiek alle sensor.*-states naar de Ampwise-portal (cloud_push) - geen platform,
geen entities die deze integratie zelf aanmaakt, alleen een achtergrondtaak die bestaande
states doorstuurt. Zie geen coordinator.py: HA's DataUpdateCoordinator is voor het ophalen van
data IN Home Assistant op een schema, niet voor het naar buiten sturen ervan - dat patroon
past hier dus niet.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_API_KEY,
    CONF_INGEST_URL,
    CONF_PUSH_INTERVAL,
    DOMAIN,
    ENTITY_DOMAIN_PREFIX,
    LOG_COOLDOWN_SECONDS,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class _PushState:
    """Houdt bij of we in storing zitten, zodat we niet elke tick loggen tijdens een uitval."""

    def __init__(self) -> None:
        self.failing = False
        self.last_logged = 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api_key = entry.data[CONF_API_KEY]
    ingest_url = entry.data[CONF_INGEST_URL]
    interval = entry.data[CONF_PUSH_INTERVAL]
    session = async_get_clientsession(hass)
    state = _PushState()

    async def _push(_now) -> None:
        # hass.states.async_all() is synchroon, geen await nodig/mogelijk.
        entities = [
            {
                "entityId": s.entity_id,
                "state": s.state,
                "unitOfMeasurement": s.attributes.get("unit_of_measurement"),
                "deviceClass": s.attributes.get("device_class"),
                "friendlyName": s.attributes.get("friendly_name"),
            }
            for s in hass.states.async_all()
            if s.entity_id.startswith(ENTITY_DOMAIN_PREFIX)
        ]

        try:
            async with session.post(
                ingest_url,
                json={"entities": entities},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientError(f"HTTP {resp.status}")
            if state.failing:
                _LOGGER.warning("Ampwise: verbinding hersteld, data wordt weer verstuurd.")
            state.failing = False
        except (aiohttp.ClientError, TimeoutError) as err:
            now = time.monotonic()
            if not state.failing or now - state.last_logged > LOG_COOLDOWN_SECONDS:
                _LOGGER.warning(
                    "Ampwise: kon data niet versturen (%s), probeer het later opnieuw.", err
                )
                state.last_logged = now
            state.failing = True

    unsub = async_track_time_interval(hass, _push, timedelta(seconds=interval))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = unsub
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unsub = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if unsub:
        unsub()
    return True
