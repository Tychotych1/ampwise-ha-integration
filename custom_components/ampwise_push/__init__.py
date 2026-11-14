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
    MAX_PUSH_INTERVAL,
    MIN_PUSH_INTERVAL,
    PRICE_FEED_MAX_SLOTS,
    PRICE_FEED_MIN_INTERVAL_SECONDS,
    PRICE_FEED_RESEND_SECONDS,
    PRICE_FEED_RETRY_SECONDS,
    REQUEST_TIMEOUT,
)
from .payload import build_catalog, price_forecast_to_send, price_retry_delay, states_to_send, update_mapped, update_price_entity

_LOGGER = logging.getLogger(__name__)


class _PortalRefused(aiohttp.ClientError):
    """De portal antwoordde, maar niet met 200 (een weigering of een fout van de portal zelf): anders dan een verbinding die niet lukte."""


class _PushState:
    """Houdt bij of we in storing zitten (zodat we niet elke tick loggen) en welke sensoren de portal wil hebben."""

    def __init__(self) -> None:
        self.failing = False
        self.last_logged = 0.0
        # De entity-id's waarvan de portal de standen wil; None = nog niet bekend (of de portal kent de lijst niet: dan alleen de energiesensoren, zie states_to_send).
        self.mapped: set[str] | None = None
        self.catalog_sent = False
        self.legacy_portal = False
        # De prijssensor die de portal noemt (priceEntity in zijn antwoord); None = geen, of een oudere portal die het veld niet kent: dan gaat er geen prijslijst mee (zie payload.py).
        self.price_entity: str | None = None
        # De handtekening en het moment (monotone klok) van de laatste prijslijst die de portal GEKREGEN heeft (een push die mislukte telt niet).
        self.price_signature: str | None = None
        self.price_sent_at: float | None = None
        # Wanneer (monotone klok) een fout bij het samenstellen van de prijslijst voor het laatst is gelogd (hooguit een per LOG_COOLDOWN_SECONDS).
        self.price_error_logged_at: float | None = None
        # Een lijst die niet is aangekomen (verbinding, time-out, antwoord niet te lezen): het aantal mislukkingen achter elkaar en het moment (monotone klok) waarvoor er geen nieuwe lijst gaat.
        self.price_failures = 0
        self.price_retry_not_before: float | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api_key = entry.data[CONF_API_KEY]
    ingest_url = entry.data[CONF_INGEST_URL]
    # Ook een entry die met een ouder formulier is aangemaakt (zonder grenzen) stuurt nooit vaker dan elke MIN_PUSH_INTERVAL seconden.
    interval = min(max(entry.data[CONF_PUSH_INTERVAL], MIN_PUSH_INTERVAL), MAX_PUSH_INTERVAL)
    session = async_get_clientsession(hass)
    state = _PushState()

    def _log_failure(message: str, *args: Any) -> None:
        now = time.monotonic()
        if not state.failing or now - state.last_logged > LOG_COOLDOWN_SECONDS:
            _LOGGER.warning(message, *args)
            state.last_logged = now
        state.failing = True

    def _log_price_error(err: Exception) -> None:
        # Alleen het soort fout, nooit de inhoud (die kan gegevens van de sensor bevatten); hooguit een melding per LOG_COOLDOWN_SECONDS.
        now = time.monotonic()
        if state.price_error_logged_at is None or now - state.price_error_logged_at > LOG_COOLDOWN_SECONDS:
            _LOGGER.warning("Ampwise: de prijslijst kon niet worden samengesteld (%s); de rest van de push gaat gewoon door.", type(err).__name__)
            state.price_error_logged_at = now

    def _price_not_delivered(now: float) -> None:
        # De lijst is niet aangekomen (of we weten het niet): niet bij elke tick opnieuw, maar met een wachttijd die bij elke mislukking verdubbelt (zie price_retry_delay).
        state.price_failures = min(state.price_failures + 1, 30)
        state.price_retry_not_before = now + price_retry_delay(state.price_failures, PRICE_FEED_RETRY_SECONDS, PRICE_FEED_RESEND_SECONDS)

    def _price_answered(now: float, signature: str | None) -> None:
        # De portal heeft geantwoord (een leesbaar antwoord, ook een weigering): de lijst telt als geprobeerd en de teller van mislukkingen begint opnieuw.
        state.price_signature = signature
        state.price_sent_at = now
        state.price_failures = 0
        state.price_retry_not_before = None

    async def _post(body: dict[str, Any]) -> Any:
        """Eén POST naar de portal; geeft het antwoord (JSON) terug of gooit bij een fout."""
        async with session.post(
            ingest_url,
            json={"version": INTEGRATION_VERSION, **body},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status == 426:
                raise _PortalRefused("de portal accepteert deze versie van de integratie niet meer - werk hem bij via HACS")
            if resp.status != 200:
                raise _PortalRefused(f"HTTP {resp.status}")
            try:
                return await resp.json()
            except (aiohttp.ContentTypeError, ValueError):
                return None

    def _handle_response(response: Any) -> None:
        # Een antwoord dat niet te lezen is (een foutpagina van een tunnel) laat wat we wisten ongemoeid; zie update_mapped.
        state.mapped, state.legacy_portal = update_mapped(state.mapped, state.legacy_portal, response)
        state.price_entity = update_price_entity(state.price_entity, response)
        if state.price_entity is None:
            # Zegt de portal later weer dat er een prijssensor is, dan hoort de lijst meteen weer mee (de eerste keer), niet pas na de herhaaltijd.
            state.price_signature = None
            state.price_sent_at = None
            state.price_failures = 0
            state.price_retry_not_before = None

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

        entities = states_to_send(hass.states.async_all(), state.mapped, state.legacy_portal, ENTITY_DOMAIN_PREFIX)
        body: dict[str, Any] = {"entities": entities}
        # De prijslijst van de prijssensor, alleen als de portal een priceEntity noemde en alleen als ze nieuw of aan herhaling toe is (zie payload.price_forecast_to_send): zonder dat is de push gelijk aan die van 1.1.0.
        # Een fout in dit hele deel (ook het lezen van de toestand) geeft een push zonder prijslijst: de gewone push gaat altijd door.
        now = time.monotonic()
        try:
            forecast, signature = price_forecast_to_send(
                hass.states.get,
                state.price_entity,
                ENTITY_DOMAIN_PREFIX,
                PRICE_FEED_MAX_SLOTS,
                state.price_signature,
                state.price_sent_at,
                now,
                PRICE_FEED_RESEND_SECONDS,
                PRICE_FEED_MIN_INTERVAL_SECONDS,
                state.price_retry_not_before,
                _log_price_error,
            )
        except Exception as err:  # noqa: BLE001 - de prijslijst mag de gewone push nooit stoppen
            _log_price_error(err)
            forecast, signature = None, None
        if forecast is not None:
            body["priceForecast"] = forecast
        try:
            # Ook zonder standen (niets gekoppeld) een bericht: de portal ziet zo dat de integratie leeft en welke versie hij heeft, en het antwoord ververst de lijst van gekoppelde sensoren.
            response = await _post(body)
            if forecast is not None:
                # Pas na een push met een LEESBAAR antwoord (een push die mislukte, of een 200 met een foutpagina van een proxy of tunnel, heeft de lijst niet bezorgd: dan met wachttijd opnieuw) en VOOR
                # het verwerken van het antwoord: zegt de portal daarin dat er geen prijssensor (meer) is, dan wist _handle_response dit weer.
                if isinstance(response, dict):
                    _price_answered(now, signature)
                else:
                    _price_not_delivered(now)
            _handle_response(response)
            if state.failing:
                _LOGGER.warning("Ampwise: verbinding hersteld, data wordt weer verstuurd.")
            state.failing = False
        except (aiohttp.ClientError, TimeoutError) as err:
            if forecast is not None:
                if isinstance(err, _PortalRefused):
                    # De portal antwoordde met iets anders dan 200 op een push met de prijslijst: de volgende push gaat zonder (dezelfde lijst elke tick opnieuw sturen helpt niet); ze komt weer bij een
                    # verandering (na PRICE_FEED_MIN_INTERVAL_SECONDS) of na PRICE_FEED_RESEND_SECONDS.
                    _price_answered(now, signature)
                else:
                    # Een verbinding die niet lukte of een time-out: de portal heeft de push misschien wel verwerkt. Opnieuw proberen mag, met een wachttijd die bij elke mislukking verdubbelt.
                    _price_not_delivered(now)
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
