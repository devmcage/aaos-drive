"""Render the original car-and-telemetry icon; requires Pillow only to rebuild it."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "custom_components/aaos_drive/brand"
TARGET.mkdir(exist_ok=True)

# Draw geometry at four times the largest output size for smooth small icons.
SCALE = 4
image = Image.new("RGBA", (512 * SCALE, 512 * SCALE))
draw = ImageDraw.Draw(image)


def box(values):
    return tuple(round(value * SCALE) for value in values)


draw.rounded_rectangle(box((24, 24, 488, 488)), radius=104 * SCALE, fill="#0288D1")
draw.polygon([box(point) for point in ((151, 133), (361, 133), (407, 251), (105, 251))], fill="white")
draw.rounded_rectangle(box((96, 227, 416, 361)), radius=31 * SCALE, fill="white")
draw.polygon([box(point) for point in ((172, 161), (340, 161), (369, 234), (143, 234))], fill="#075985")
draw.rounded_rectangle(box((112, 342, 165, 396)), radius=12 * SCALE, fill="white")
draw.rounded_rectangle(box((347, 342, 400, 396)), radius=12 * SCALE, fill="white")
draw.ellipse(box((122, 271, 167, 316)), fill="#0288D1")
draw.ellipse(box((345, 271, 390, 316)), fill="#0288D1")
draw.rounded_rectangle(box((192, 312, 320, 333)), radius=10 * SCALE, fill="#075985")
points = ((184, 207), (214, 195), (245, 211), (276, 178), (321, 192))
draw.line([box(point) for point in points], fill="#69F0AE", width=9 * SCALE, joint="curve")
for x, y in points:
    draw.ellipse(box((x - 5, y - 5, x + 5, y + 5)), fill="#69F0AE")

for size, filename in ((256, "icon.png"), (512, "icon@2x.png")):
    image.resize((size, size), Image.Resampling.LANCZOS).save(TARGET / filename, optimize=True)
    print(f"Rendered {filename}: {size} x {size}")
