# AAOS brand artwork

`app-icon-512.png` is the current official AAOS Logging Google Play icon, copied from the app project’s `store-assets/play/app-icon-512.png`.
Keep this source artwork intact: its white car and mint-green winding route identify
the AAOS brand.

`tools/build_brand.py` produces the Home Assistant brand assets:

- `custom_components/aaos_drive/brand/icon.png`: a 256px size variant.
- `custom_components/aaos_drive/brand/icon@2x.png`: an exact copy of the official
  512px PNG, also used by the GitHub README and trip dashboard header.

The dashboard uses Home Assistant's typography, spacing and theme colors around
the original icon. Its supplied full-square dark background maintains contrast in both
light and dark interfaces. The logo is not recolored or redrawn.

To rebuild the size variants, install Pillow in a development environment and
run `python tools/build_brand.py`. Pillow is not a Home Assistant dependency.
