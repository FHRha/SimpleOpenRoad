"""Core constants used by API, CLI and routing layers."""

DEFAULT_CONFIG_PATH = "config/config.yaml"
DEFAULT_DB_PATH = "data/gateway.db"

HEADER_API_KEY = "x-api-key"
HEADER_ADMIN_KEY = "x-admin-key"
HEADER_AUTHORIZATION = "authorization"

STATUS_UNKNOWN = "unknown"
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_DEGRADED = "degraded"
STATUS_BLOCKED = "blocked"

ROUTE_STRICT_PRIORITY = "strict_priority"
ROUTE_WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
ROUTE_RANDOM_BY_WEIGHT = "random_by_weight"
ROUTE_LEAST_RECENTLY_USED = "least_recently_used"
ROUTE_LEAST_ERRORS = "least_errors"
