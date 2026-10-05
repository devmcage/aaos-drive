"""Package the official AAOS icon at Home Assistant's standard icon sizes.

The source artwork is preserved. Pillow is needed only to rebuild the 256px
variant; the 512px variant is an exact copy of the supplied official PNG.
"""

from pathlib import Path

from shutil import copyfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "icon/app-icon-512.png"
TARGET = ROOT / "custom_components/aaos_drive/brand"
TARGET.mkdir(exist_ok=True)

with Image.open(SOURCE) as image:
    if image.format != "PNG" or image.size != (512, 512):
        raise ValueError("The official AAOS source must be a 512 x 512 PNG")
    image.resize((256, 256), Image.Resampling.LANCZOS).save(TARGET / "icon.png", optimize=True)
copyfile(SOURCE, TARGET / "icon@2x.png")
print("Packaged official AAOS icon: 256px and original 512px artwork")
