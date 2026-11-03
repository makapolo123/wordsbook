"""生成 PWA 图标（本地一次性工具）。

输出到 docs/icons/：
  icon-192.png / icon-512.png      普通图标（圆角底）
  maskable-512.png                 安卓自适应图标（图形收在安全区内）
  apple-touch-icon-180.png         iOS 主屏图标（必须是满底方形，否则会显示黑底）

用法：.venv/Scripts/python.exe tools/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "icons"
ACCENT = (53, 95, 73, 255)      # #355F49
PALE = (238, 245, 240, 255)    # #EEF5F0
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_icon(size: int, *, rounded: bool, padding_ratio: float) -> Image.Image:
    scale = 4  # 先画大图再缩小，边缘更干净
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if rounded:
        radius = int(canvas * 0.22)
        draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=ACCENT)
    else:
        draw.rectangle([0, 0, canvas - 1, canvas - 1], fill=ACCENT)

    # 中央浅色圆盘 + 汉字
    pad = int(canvas * padding_ratio)
    draw.ellipse([pad, pad, canvas - pad, canvas - pad], fill=PALE)
    font = load_font(int((canvas - pad * 2) * 0.62))
    text = "词"
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((canvas - (box[2] - box[0])) / 2 - box[0], (canvas - (box[3] - box[1])) / 2 - box[1]),
        text,
        font=font,
        fill=ACCENT,
    )
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, True, 0.16),
        ("icon-512.png", 512, True, 0.16),
        ("maskable-512.png", 512, False, 0.24),
        ("apple-touch-icon-180.png", 180, False, 0.17),
    ]
    for name, size, rounded, padding in targets:
        image = draw_icon(size, rounded=rounded, padding_ratio=padding)
        if name.startswith("apple-touch") or name.startswith("maskable"):
            # iOS / maskable 不接受透明通道
            flat = Image.new("RGB", (size, size), ACCENT[:3])
            flat.paste(image, (0, 0), image)
            flat.save(OUT / name, "PNG")
        else:
            image.save(OUT / name, "PNG")
        print(f"  写出 docs/icons/{name}（{size}×{size}）")
    print("完成。")


if __name__ == "__main__":
    main()
