from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a labeled 3x2 storyboard sheet.")
    parser.add_argument("output", type=Path)
    parser.add_argument("frames", nargs=12, metavar="ITEM")
    args = parser.parse_args()

    items = list(zip(args.frames[::2], args.frames[1::2], strict=True))
    frame_width, frame_height, label_height = 640, 360, 52
    canvas = Image.new("RGB", (frame_width * 3, (frame_height + label_height) * 2), "#0b0d10")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    for index, (label, source) in enumerate(items):
        row, column = divmod(index, 3)
        x, y = column * frame_width, row * (frame_height + label_height)
        with Image.open(source) as image:
            frame = image.convert("RGB").resize(
                (frame_width, frame_height), Image.Resampling.LANCZOS
            )
        canvas.paste(frame, (x, y))
        draw.rectangle((x, y + frame_height, x + frame_width, y + frame_height + label_height), fill="#11161d")
        draw.text((x + 18, y + frame_height + 12), label, fill="#f0c674", font=font)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, format="PNG")


if __name__ == "__main__":
    main()
