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
# Grenzen voor het interval: een interval van 0 of lager laat de integratie zonder pauze sturen (honderden berichten per seconde), een heel groot interval maakt de gegevens in de portal oud.
MIN_PUSH_INTERVAL = 5  # seconden
MAX_PUSH_INTERVAL = 3600  # seconden

ENTITY_DOMAIN_PREFIX = "sensor."
REQUEST_TIMEOUT = 10  # seconden - zelfde orde van grootte als de portal se eigen HTTP-timeouts
LOG_COOLDOWN_SECONDS = 3600  # herhaal een waarschuwing tijdens een aanhoudende storing max 1x/uur

# Het versienummer dat bij elke push meegaat (hetzelfde als manifest.json): de portal ziet zo welke integratie er draait en markeert een push zonder versie als "oude integratie".
INTEGRATION_VERSION = "1.2.0"
# De lijst van alle sensoren (zonder standen) gaat bij het opstarten en daarna zo vaak naar de portal.
CATALOG_INTERVAL = timedelta(days=1)

# De prijslijst van de prijssensor (raw_today en raw_tomorrow, of forecast van de Zonneplan-integratie, zie payload.py): alleen als de portal in zijn antwoord een priceEntity noemt. Ze gaat mee bij de eerste push daarna, bij een verandering
# van de inhoud (de prijzen van morgen komen zodra de leverancier ze publiceert, meestal in de loop van de middag) en anders hooguit eens per PRICE_FEED_RESEND_SECONDS, zodat een gemiste push geen gat laat: niet bij
# elke push van 5 of 30 seconden. Dezelfde herhaaltijd (30 minuten) als de portal verwacht.
PRICE_FEED_RESEND_SECONDS = 30 * 60
# Een veranderde lijst gaat hooguit zo vaak mee: de portal verwerkt per account hooguit 12 lijsten per uur; een sensor waarvan de attributen bij elke tick veranderen zou anders elke 5 tot 30 seconden
# 10 tot 20 kB sturen die de portal toch weggooit. Elke verzending ligt minstens zo ver na de vorige (een herhaling na 30 minuten komt er nog bij, maar ook die telt vanaf de laatste verzending), dus
# hooguit 10 per uur en dus een marge van 2 onder de 12 van de portal. De eerste lijst na het opstarten of na een nieuwe melding van de portal gaat meteen mee.
PRICE_FEED_MIN_INTERVAL_SECONDS = 6 * 60
# Een lijst die niet is aangekomen (de verbinding lukte niet, een time-out of een antwoord dat niet te lezen was) wordt niet bij elke tick opnieuw gestuurd: de eerste nieuwe poging komt na zo veel
# seconden en elke volgende mislukking verdubbelt de wachttijd, tot hooguit PRICE_FEED_RESEND_SECONDS. Een time-out waarbij de portal de push toch verwerkte zou anders de lijsten per uur van de portal opmaken.
PRICE_FEED_RETRY_SECONDS = 60
# Hooguit zoveel items in de lijst per push: de grens van de portal voor een prijslijst (drie dagen van 96 kwartieren). Een lijst met meer items weigert de portal helemaal, dus een langere lijst van de sensor
# wordt hier afgekapt tot de eerste items in de volgorde van de sensor. Een gewone lijst (vandaag en morgen) heeft er 192, die van de Zonneplan-integratie 160 tot ongeveer 260.
PRICE_FEED_MAX_SLOTS = 288
