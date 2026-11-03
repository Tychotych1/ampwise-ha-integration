"""Constanten voor de Ampwise push-integratie."""
from datetime import timedelta

DOMAIN = "ampwise_push"

CONF_API_KEY = "api_key"
CONF_INGEST_URL = "ingest_url"
CONF_PUSH_INTERVAL = "push_interval"

# Als config_flow-veld (niet hardcoded) zodat een droogloop tegen een lokale dev-server kan
# wijzen zonder de integratie-broncode aan te passen.
DEFAULT_INGEST_URL = "https://ampwise.nl/api/ingest"
DEFAULT_PUSH_INTERVAL = 30  # seconden

ENTITY_DOMAIN_PREFIX = "sensor."
REQUEST_TIMEOUT = 10  # seconden - zelfde orde van grootte als de portal se eigen HTTP-timeouts
LOG_COOLDOWN_SECONDS = 3600  # herhaal een waarschuwing tijdens een aanhoudende storing max 1x/uur

# Het versienummer dat bij elke push meegaat (hetzelfde als manifest.json): de portal ziet zo welke integratie er draait en markeert een push zonder versie als "oude integratie".
INTEGRATION_VERSION = "1.1.0"
# De lijst van alle sensoren (zonder standen) gaat bij het opstarten en daarna zo vaak naar de portal.
CATALOG_INTERVAL = timedelta(days=1)
