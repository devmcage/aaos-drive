"""Check distribution boundaries and the wrapper's pinned library dependency."""

import ast
from email.parser import BytesParser
import json
from pathlib import Path
import tarfile
import tomllib
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "packages/aaos-logging-drive"
SOURCE = PROJECT / "src/aaos_logging_drive"
metadata = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
version = metadata["version"]
manifest = json.loads((ROOT / "custom_components/aaos_drive/manifest.json").read_text())
assert manifest["requirements"] == [f"{metadata['name']}=={version}"], "HA requirement must pin the built library"
version_nodes = ast.parse((SOURCE / "__init__.py").read_text()).body
assert any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
           and ast.literal_eval(node.value) == version for node in version_nodes)
for path in SOURCE.glob("*.py"):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        imported = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        assert not any(name.split(".")[0] in {"homeassistant", "custom_components"} for name in imported), path.name
wheel = ROOT / f"dist/aaos_logging_drive-{version}-py3-none-any.whl"
with ZipFile(wheel) as archive:
    assert archive.testzip() is None
    for name in archive.namelist():
        assert name.startswith(("aaos_logging_drive/", f"aaos_logging_drive-{version}.dist-info/")), name
        assert not any(part in name for part in (".verification", "custom_components", ".sqlite", "__pycache__")), name
    info = BytesParser().parsebytes(archive.read(f"aaos_logging_drive-{version}.dist-info/METADATA"))
    assert info["Name"] == metadata["name"] and info["Version"] == version
    assert not any("homeassistant" in requirement.lower() for requirement in info.get_all("Requires-Dist", []))
    for path in SOURCE.iterdir():
        if path.is_file():
            assert archive.read("aaos_logging_drive/"+path.name).replace(b"\r\n", b"\n") == path.read_bytes().replace(b"\r\n", b"\n"), path.name
with tarfile.open(ROOT / f"dist/aaos_logging_drive-{version}.tar.gz") as archive:
    names = archive.getnames()
    for name in names:
        assert not any(part in name for part in (".verification", "custom_components", ".sqlite", "__pycache__")), name
    assert any(name.endswith("/tests/test_standalone.py") for name in names)
    assert any(name.endswith("/pyproject.toml") for name in names)
print(f"Verified standalone wheel/source distribution and HA dependency pin: {metadata['name']}=={version}")
