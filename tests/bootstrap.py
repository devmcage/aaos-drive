"""Load the portable importer without installing Home Assistant on Windows."""

from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".verification" / "deps"))

# Do not execute HA's integration entry point for portable parser/transport tests.
for name, path in (("custom_components", ROOT / "custom_components"), ("custom_components.aaos_drive", ROOT / "custom_components" / "aaos_drive")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
