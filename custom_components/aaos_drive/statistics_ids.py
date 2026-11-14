"""Stable Home Assistant Recorder identifiers, independent of entity names."""

import hashlib
import re

def statistic_id(entry_id, field):
    # Home Assistant's ULID entry IDs contain capitals. Recorder requires
    # lowercase slugs without consecutive/leading/trailing underscores.
    entry_slug = re.sub(r"[^a-z0-9]+", "_", entry_id.lower()).strip("_")
    slug = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
    digest = hashlib.sha256(field.encode()).hexdigest()[:8]
    return f"aaos_drive:{entry_slug}_{slug}_{digest}"
