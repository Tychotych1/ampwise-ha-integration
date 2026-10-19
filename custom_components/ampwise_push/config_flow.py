"""Config flow voor de Ampwise push-integratie."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_INGEST_URL,
    CONF_PUSH_INTERVAL,
    DEFAULT_INGEST_URL,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


async def _validate_api_key(hass: HomeAssistant, ingest_url: str, api_key: str) -> bool:
    """Stuurt een lege entities-array - valideert de sleutel zonder al echte data te sturen."""
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            ingest_url,
            json={"entities": []},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            return resp.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


class AmpwiseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow - vraagt een API-sleutel, ingest-URL en push-interval."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            valid = await _validate_api_key(
                self.hass, user_input[CONF_INGEST_URL], user_input[CONF_API_KEY]
            )
            if valid:
                await self.async_set_unique_id(user_input[CONF_API_KEY][:16])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Ampwise", data=user_input)
            errors["base"] = "invalid_auth"

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_INGEST_URL, default=DEFAULT_INGEST_URL): str,
                vol.Required(CONF_PUSH_INTERVAL, default=DEFAULT_PUSH_INTERVAL): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
