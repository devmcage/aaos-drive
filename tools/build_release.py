"""Build an integration-only ZIP with the maintained user documentation."""

import importlib.util
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aaos_constants", ROOT / "custom_components/aaos_drive/const.py")
constants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(constants)

for document in ("INSTALLATION.md", "ATTRIBUTES.md"):
    if not (ROOT / "docs" / document).is_file():
        raise ValueError(f"Missing user documentation: {document}")
reference = (ROOT / "docs/ATTRIBUTES.md").read_text(encoding="utf-8")
for group, fields in (("telemetry", constants.TELEMETRY_FIELDS), ("trip", constants.TRIP_FIELDS),
                      ("weather", constants.WEATHER_FIELDS), ("route", ("recordedAt", "latitude", "longitude"))):
    missing = [f"{group}.{key}" for key in fields if f"`{group}.{key}`" not in reference]
    if missing:
        raise ValueError(f"Undocumented fields: {', '.join(missing)}")
strings = ROOT / "custom_components/aaos_drive/strings.json"
translations = ROOT / "custom_components/aaos_drive/translations"
translations.mkdir(exist_ok=True)
(translations / "en.json").write_text(strings.read_text(encoding="utf-8"), encoding="utf-8")

version = json.loads((ROOT / "custom_components/aaos_drive/manifest.json").read_text())["version"]
release_dir = ROOT / "release"
release_dir.mkdir(exist_ok=True)
target = release_dir / f"aaos-drive-{version}.zip"
paths = [ROOT / "README.md", ROOT / "LICENSE", ROOT / "hacs.json"]
for folder in ("custom_components/aaos_drive", "docs"):
    paths.extend(path for path in (ROOT / folder).rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
with ZipFile(target, "w", ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        archive.write(path, path.relative_to(ROOT).as_posix())
with ZipFile(target) as archive:
    assert archive.testzip() is None
print(f"Built {target.name}: {len(paths)} files; {len(constants.TELEMETRY_FIELDS)} telemetry fields")
