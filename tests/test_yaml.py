from pathlib import Path
import json
import unittest

from . import bootstrap
import yaml


class YamlTests(unittest.TestCase):
    def test_action_definitions_have_vehicle_selectors(self):
        services = yaml.safe_load((bootstrap.ROOT / "custom_components/aaos_drive/services.yaml").read_text())
        self.assertEqual(set(services), {"get_catalog", "get_trip", "list_trips", "get_index", "get_history", "get_history_fields"})
        for service in services.values():
            self.assertTrue(service["fields"]["config_entry_id"]["required"])
            self.assertEqual(service["fields"]["config_entry_id"]["selector"]["config_entry"]["integration"], "aaos_drive")
        self.assertIn("trip_id", services["get_history"]["fields"])

    def test_manifest_and_translations(self):
        root = bootstrap.ROOT / "custom_components/aaos_drive"
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], "aaos_drive")
        self.assertIn("application_credentials", manifest["dependencies"])
        english = json.loads((root / "translations/en.json").read_text())
        self.assertEqual(english, json.loads((root / "strings.json").read_text()))
