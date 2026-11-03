"""Gedeelde opzet voor de tests met een nagebootste Home Assistant (pytest-homeassistant-custom-component)."""
import asyncio
import sys

import pytest
import pytest_socket

# Vroeg importeren (bij het verzamelen van de tests): zo staat custom_components van deze repository al in sys.modules voordat de fixture "hass" dat van de testbibliotheek (testing_config)
# laadt, en vindt Home Assistant de integratie ampwise_push.
import custom_components.ampwise_push  # noqa: F401

if sys.platform == "win32":
    # De testbibliotheek van Home Assistant is voor Linux gemaakt: ze blokkeert elke socket behalve unix-sockets (pytest_socket.disable_socket(allow_unix_socket=True)), want daar gebruikt
    # asyncio een unix-socketpaar voor zijn interne verbinding. Op Windows maakt asyncio daarvoor een gewone socket en faalt elke test al bij het aanmaken van de event loop
    # (SocketBlockedError in de fixture event_loop). Hier gaat alleen dat blokkeren van het AANMAKEN van een socket uit. Wat de bibliotheek eerst instelt, blijft: een verbinding
    # mag alleen naar 127.0.0.1 (pytest_socket.socket_allow_hosts), dus een test die per ongeluk echt het internet op gaat, faalt nog steeds. Op Linux (CI) verandert er niets.
    pytest_socket.disable_socket = lambda allow_unix_socket=False: None
    # Home Assistant gebruikt op Windows de standaard (proactor) event loop, maar aiodns (via aiohttp) werkt daar alleen met een selector-loop: zonder dit faalt het aanmaken van elke
    # aiohttp-sessie met "aiodns needs a SelectorEventLoop on Windows". De testbibliotheek zet het beleid zelf vast, dus de fabriek van het bestaande beleid wordt aangepast.
    asyncio.get_event_loop_policy()._loop_factory = asyncio.SelectorEventLoop  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Laat Home Assistant de map custom_components van deze repository laden."""
    yield
