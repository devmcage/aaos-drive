"""Read-only AAOS Logging Drive client and recorded vehicle data processing."""

from .api import DriveAuthError, DriveError, DriveNotFoundError, ReadOnlyDrive, folder_id
from .battery_capacity import capacity_telemetry
from .client import AAOSDriveClient
from .const import READ_SCOPE, readonly_grant
from .energy import EnergyReview, effective_telemetry, review_energy
from .history import HistoryStore, sync_history
from .model import Artifact, ExportNotReady, InvalidExport, Manifest, Snapshot, archive_trips, trip_summary
from .repository import DriveRepository

__version__ = "0.1.0"

__all__ = [
    "AAOSDriveClient", "Artifact", "DriveAuthError", "DriveError", "DriveNotFoundError",
    "DriveRepository", "EnergyReview", "ExportNotReady", "HistoryStore", "InvalidExport",
    "Manifest", "READ_SCOPE", "ReadOnlyDrive", "Snapshot", "archive_trips",
    "capacity_telemetry", "effective_telemetry", "folder_id", "readonly_grant",
    "review_energy", "sync_history", "trip_summary",
]
