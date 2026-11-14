"""Home Assistant configuration and shared AAOS contract constants."""

from aaos_logging_drive.const import BINARY_FIELDS, READ_SCOPE, readonly_grant

DOMAIN = "aaos_drive"
NAME = "AAOS Logging Drive"
DEFAULT_SCAN_MINUTES = 15
DEFAULT_STALE_HOURS = 24
