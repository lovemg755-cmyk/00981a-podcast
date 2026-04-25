"""產生 podcast 封面：1400×1400 PNG，活力科技感。

設計：
- 深紫到電光藍漸層背景
- 細緻六角網格覆蓋層
- 發光股價曲線（高斯模糊光暈）
- 大字 00981A + 副標
- 右下角發光指示燈
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1400, 1400
OUT = Path(__file__).resolve().parents[1] / "assets" / "cover.png"

# ===== 色票（科技感）=====
# 深邃背景三段
TOP = (12, 8, 38)        # 深紫黑
MID = (22, 50, 130)      # 鈷藍
BOTTOM = (5, 80, 165)    # 電光藍
ACCENT = (0, 230, 255)   # 主強調色（青藍）
ACCENT2 = (255, 90, 200) # 次強調色（霓虹粉）
GRID = (255, 255, 255, 18)  # 極淡白色網格


def vertical_gradient() -> Image.Image:
    img = Image.new("RGB", (W, H), TOP)
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        if t < 0.5:
            u = t * 2
            c = tuple(int(TOP[i] + (MID[i] - TOP[i]) * u) for i in range(3))
        else:
            u = (t - 0.5) * 2
            c = tuple(int(MID[i] + (BOTTOM[i] - MID[i]) * u) for i in range(3))
        for x in range(W):
            px[x, y] = c
    # 加一個從右下到左上的徑向光暈（讓整體更立體）
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W * 0.4, H * 0.4, W * 1.4, H * 1.4),
               fill=(0, 200, 255, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=180))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    return img


def hex_grid(img: Image.Image) -> Image.Image:
    """覆蓋一層淡淡的六角形網格。"""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    size = 55
    dx = size * math.sqrt(3)
    dy = size * 1.5

    rows = int(H / dy) + 2
    cols = int(W / dx) + 2
    for r in range(rows):
        for col in range(cols):
            cx = col * dx + (dx / 2 if r % 2 else 0)
            cy = r * dy
            pts = []
            for i in range(6):
                a = math.pi / 3 * i + math.pi / 6
                pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
            d.polygon(pts, outline=GRID, width=1)
    return Image.alpha_composite(img, overlay)


def stock_curve(img: Image.Image) -> Image.Image:
    """一條由左下往右上、有起伏的發光股價曲線。"""
    random.seed(42)
    pts: list[tuple[float, float]] = []
    base_start = H * 0.72
    base_end = H * 0.48  # 整體上升
    n = 32
    for i in range(n + 1):
        t = i / n
        x = 60 + t * (W - 120)
        base = base_start + (base_end - base_start) * t
        # 加上週期性 + 隨機波動
        wave = math.sin(t * math.pi * 3.5) * 30
        noise = random.uniform(-25, 25)
        y = base + wave + noise
        pts.append((x, y))

    # 1. 寬版高斯模糊光暈
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(pts, fill=ACCENT + (180,), width=22, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(radius=18))
    img = Image.alpha_composite(img, glow)

    # 2. 二級光暈（霓虹粉，較窄）
    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(glow2)
    gd2.line(pts, fill=ACCENT2 + (140,), width=10, joint="curve")
    glow2 = glow2.filter(ImageFilter.GaussianBlur(radius=10))
    img = Image.alpha_composite(img, glow2)

    # 3. 主線（清晰白色細線）
    line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    ld.line(pts, fill=(255, 255, 255, 245), width=4, joint="curve")
    img = Image.alpha_composite(img, line)

    # 4. 端點亮點
    end_x, end_y = pts[-1]
    dot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot)
    for r, alpha in [(40, 80), (24, 160), (12, 230)]:
        dd.ellipse((end_x - r, end_y - r, end_x + r, end_y + r),
                   fill=ACCENT + (alpha,))
    dot = dot.filter(ImageFilter.GaussianBlur(radius=4))
    img = Image.alpha_composite(img, dot)
    dd2 = ImageDraw.Draw(img)
    dd2.ellipse((end_x - 8, end_y - 8, end_x + 8, end_y + 8),
                fill=(255, 255, 255, 255))
    return img


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        # Windows
        "C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/mingliub.ttc" if bold else "C:/Windows/Fonts/mingliu.ttc",
        # macOS / Linux 後備
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_text_with_glow(
    img: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    pos: tuple[int, int],
    color: tuple[int, int, int],
    glow_color: tuple[int, int, int] = ACCENT,
    glow_radius: int = 20,
) -> Image.Image:
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text(pos, text, font=font, fill=glow_color + (200,))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=glow_radius))
    img = Image.alpha_composite(img, glow)
    main = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(main)
    md.text(pos, text, font=font, fill=color + (255,))
    return Image.alpha_composite(img, main)


def centered_x(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox(text)
    return (W - (bbox[2] - bbox[0])) // 2


def add_text(img: Image.Image) -> Image.Image:
    # 上方小標 ETF DAILY BRIEF
    tag_font = find_font(48, bold=True)
    tag = "ETF · DAILY BRIEF"
    img = draw_text_with_glow(
        img, tag, tag_font,
        (centered_x(tag, tag_font), 130),
        color=(170, 220, 255),
        glow_color=ACCENT,
        glow_radius=12,
    )

    # 主標 00981A — 超大字
    title_font = find_font(360, bold=True)
    title = "00981A"
    img = draw_text_with_glow(
        img, title, title_font,
        (centered_x(title, title_font), 200),
        color=(255, 255, 255),
        glow_color=ACCENT,
        glow_radius=28,
    )

    # 中文副標
    sub_font = find_font(108, bold=True)
    sub = "每日持股觀察"
    img = draw_text_with_glow(
        img, sub, sub_font,
        (centered_x(sub, sub_font), 1020),
        color=(255, 255, 255),
        glow_color=ACCENT2,
        glow_radius=18,
    )

    # 底部分隔線 + tag
    line = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    ld.line([(W * 0.32, 1200), (W * 0.68, 1200)], fill=ACCENT + (180,), width=3)
    img = Image.alpha_composite(img, line)

    foot_font = find_font(46)
    foot = "AI 主播小愛 · 每交易日 17:30"
    img = draw_text_with_glow(
        img, foot, foot_font,
        (centered_x(foot, foot_font), 1240),
        color=(180, 210, 240),
        glow_color=ACCENT,
        glow_radius=10,
    )
    return img


def main() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = vertical_gradient()
    img = hex_grid(img)
    img = stock_curve(img)
    img = add_text(img)
    img = img.convert("RGB")
    img.save(OUT, "PNG", optimize=True)
    print(f"封面已輸出：{OUT}  ({OUT.stat().st_size // 1024} KB)")
    return OUT


if __name__ == "__main__":
    main()
