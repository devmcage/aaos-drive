# Standalone library and Home Assistant wrapper

The `PyPi` branch separates this project into two distributions:

| Distribution | Location | Responsibility |
| --- | --- | --- |
| `aaos-logging-drive` 0.1.0 | `packages/aaos-logging-drive` | Google Drive reads, complete-generation validation, import/retry logic, local history, vehicle measurements, battery/fuel processing and data queries. |
| `aaos_drive` 0.5.0a1 | `custom_components/aaos_drive` | HA OAuth linking, scheduling, config storage, devices/entities, visibility, Recorder statistics, actions, WebSocket API and dashboard. |

The library is an independently installable Python project with its own
`pyproject.toml`, license, README, public API and standalone tests. Its wheel and
source distribution contain no Home Assistant implementation or dependencies.
The wrapper imports the installed library; it does not bundle a fallback copy.
Both distributions can live in this repository and be versioned/released separately.

The integration manifest pins `aaos-logging-drive==0.1.0`. **That version must be
published to PyPI before releasing this wrapper through HACS.** This branch is a
development preview, not a replacement for the published stable 0.4.8 release.
No PyPI upload or account configuration is performed by the build commands.

## Standalone use

See the [library README](../packages/aaos-logging-drive/README.md) for a complete
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
- `release/aaos-drive-0.5.0a1.zip` — Home Assistant wrapper and user documentation.

The package checker rejects HA imports in the library, a mismatched dependency
pin, library builds differing from source, and unintended files in the archives.
The standalone test process does not import HA stubs or the custom component.
CI installs the built wheel for those tests, separately from adapter tests.

## Test the unpublished package with Home Assistant Core

Use a development Core environment, with this package installed into the same
Python environment as Home Assistant:

```sh
python -m pip install -e ./packages/aaos-logging-drive
hass --skip-pip-packages aaos-logging-drive
```

Copy/symlink the wrapper into that development installation's `custom_components`.
This follows Home Assistant's [unpublished-library development workflow](https://contributors.home-assistant.io/core/integrations/manifest/#requirements).
Do not install the preview as a normal HACS update before its PyPI dependency is
available; HA otherwise tries to download that exact version and setup fails.

## Release order

1. Check ownership/availability of the PyPI project name, finalize the library version, and build/test both artifacts.
2. Publish the library wheel and source distribution using a PyPI account or configured Trusted Publisher. No credentials belong in this repository.
3. Verify the version can be installed from PyPI in a fresh environment.
4. Ensure the wrapper manifest pins that exact version, then publish the tested wrapper through the usual GitHub/HACS release process.

The upload command, when publishing has been authorized and authentication is
configured externally, is `python -m twine upload dist/*`. Building alone does not
publish anything. A separate source repository can be made from
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
