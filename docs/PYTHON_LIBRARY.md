# Standalone library and Home Assistant wrapper

This repository contains two distributions:

| Distribution | Location | Responsibility |
| --- | --- | --- |
| `aaos-logging-drive` 0.1.0 | `packages/aaos-logging-drive` | Google Drive reads, complete-generation validation, import/retry logic, local history, vehicle measurements, battery/fuel processing and data queries. |
| `aaos_drive` 0.5.0 | `custom_components/aaos_drive` | HA OAuth linking, scheduling, config storage, devices/entities, visibility, Recorder statistics, actions, WebSocket API and dashboard. |

The library is an independently installable Python project with its own
`pyproject.toml`, license, README, public API and standalone tests. Its wheel and
source distribution contain no Home Assistant implementation or dependencies.
The wrapper imports the installed library; it does not bundle a fallback copy.
Both distributions live in this repository and are versioned/released separately.
This is the only supported Home Assistant integration architecture.

The integration manifest pins the published `aaos-logging-drive==0.1.0` package.
Home Assistant installs it automatically when the wrapper loads. HACS manages
the wrapper's files and updates; users do not need to run pip commands themselves.
No PyPI upload or account configuration is performed by local build commands.

## Standalone use

See the [library README on PyPI](https://pypi.org/project/aaos-logging-drive/0.1.0/) for a complete
asynchronous example and the public API. The host application supplies an
`aiohttp.ClientSession`, an async OAuth token provider and the selected car folder.
`AAOSDriveClient.from_google_drive(..., history_path=...)` handles complete imports
and historical queries. Home Assistant is not needed to use the package.

The library makes only Drive GET requests. A standalone application must arrange
its own Google read-only consent and token refresh. Credentials stay outside the
history database; the library never embeds an OAuth client ID, secret or token.

## Build and verify

Run these commands from the repository root, using a virtual environment:

```sh
python -m pip install build twine
python -m build packages/aaos-logging-drive --outdir dist
python -m twine check dist/*
python tools/check_packages.py
python -m pip install dist/aaos_logging_drive-0.1.0-py3-none-any.whl
python -m unittest discover -s packages/aaos-logging-drive/tests -v
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -t . -q
node tests/test_dashboard.js
python tools/build_release.py
```

Artifacts are produced independently:

- `dist/aaos_logging_drive-0.1.0-py3-none-any.whl` — standalone wheel.
- `dist/aaos_logging_drive-0.1.0.tar.gz` — standalone source project, including its tests.
- `release/aaos-drive-0.5.0.zip` — Home Assistant wrapper and user documentation.

The package checker rejects HA imports in the library, a mismatched dependency
pin, library builds differing from source, and unintended files in the archives.
The standalone test process does not import HA stubs or the custom component.
CI installs the built wheel for those tests, separately from adapter tests.

## Develop future library changes with Home Assistant Core

Use a development Core environment, with this package installed into the same
Python environment as Home Assistant:

```sh
python -m pip install -e ./packages/aaos-logging-drive
hass --skip-pip-packages aaos-logging-drive
```

Copy/symlink the wrapper into that development installation's `custom_components`.
This follows Home Assistant's [unpublished-library development workflow](https://contributors.home-assistant.io/core/integrations/manifest/#requirements).
For future releases, publish any new pinned library version to PyPI before
releasing the corresponding wrapper; otherwise normal HA setup cannot resolve
the dependency. Released wrapper 0.5.0 uses the published library version 0.1.0.

## Release order

1. Check ownership/availability of the PyPI project name, finalize the library version, and build/test both artifacts.
2. Publish the library wheel and source distribution using a PyPI account or configured Trusted Publisher. No credentials belong in this repository.
3. Verify the version can be installed from PyPI in a fresh environment.
4. Ensure the wrapper manifest pins that exact version, then publish the tested wrapper through the usual GitHub/HACS release process.

The **Publish library to PyPI** workflow, in
`.github/workflows/publish-library.yml`, publishes the library independently of
Home Assistant releases. Run it manually on `main`, supplying the exact version
in the library's `pyproject.toml`. It builds and checks the wheel/source archives,
runs the standalone and wrapper tests, uploads only the tested distributions,
then verifies a fresh installation directly from PyPI.

The PyPI Trusted Publisher must authorize this repository and the workflow
filename `publish-library.yml`. The publishing job uses the GitHub environment
`pypi`; a publisher with an unrestricted environment also permits it. Only the
publishing job receives permission to obtain a short-lived publishing token.
No PyPI password or permanent API token is configured in the repository.
Ordinary pushes and Home Assistant releases do not trigger a PyPI upload.
Published version numbers cannot be reused for changed distributions.

Building locally alone does not publish anything. A separate source repository can be made from
`packages/aaos-logging-drive` without changing the installed package API.

## Existing configurations and data

The integration domain, config-entry identity, entity IDs, library field keys,
SQLite schema and history processing version are preserved. Moving the code does
not force a new Drive import or clear Recorder data. HA owns the accepted-head
file and OAuth grant as before; it passes validated state and its executor into
the library. The library accepts a generation only after local history is complete.

Recorder-specific statistic IDs and device-class mapping remain in the wrapper.
The library exposes generic units, quantities, timestamped data, hourly aggregates
and an opaque statistics checkpoint. HA registers those aggregates through its
public Recorder APIs; standalone consumers can report from them independently.
