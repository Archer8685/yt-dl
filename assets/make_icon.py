"""產生 App 圖示：assets/icon.png（1024）、icon-128.png、icon.ico（Windows）、icon.icns（macOS）。

配色沿用網頁的 --accent-2 → --accent → --pink 漸層；白色「播放＋下載」符號在 16px 也看得清楚。
用法：python assets/make_icon.py（需要 Pillow）
"""
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
S = 1024          # 輸出尺寸
K = 4             # 超取樣倍數，縮小後邊緣平滑
N = S * K
STOPS = [(0.0, (82, 39, 255)), (0.55, (139, 92, 246)), (1.0, (255, 107, 213))]  # #5227ff #8b5cf6 #ff6bd5


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(size):
    """左上到右下的三色漸層。"""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            for (t0, c0), (t1, c1) in pairwise(STOPS):
                if t <= t1:
                    px[x, y] = lerp(c0, c1, (t - t0) / (t1 - t0))
                    break
    return img.resize((size, size), Image.BICUBIC)


def rounded_mask(size, inset, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((inset, inset, size - inset, size - inset), radius, fill=255)
    return m


def glyph(size):
    """白色符號：圓角播放三角形，下方一條托盤線 —— 「影片」＋「下載」。"""
    g = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(g)
    u = size / 1024
    # 播放三角形（以粗描邊的圓角三角形近似）
    tri = [(392 * u, 300 * u), (392 * u, 640 * u), (690 * u, 470 * u)]
    d.polygon(tri, fill=255)
    d.line([*tri, tri[0]], fill=255, width=round(70 * u), joint="curve")
    for x, y in tri:
        r = 35 * u
        d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    # 托盤（下載的落點）
    d.rounded_rectangle((300 * u, 742 * u, 724 * u, 800 * u), radius=29 * u, fill=255)
    return g


def build():
    inset, radius = round(N * 0.06), round(N * 0.21)
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    shape = rounded_mask(N, inset, radius)

    # 柔和陰影，讓圖示在淺色桌面上也有立體感
    shadow = Image.new("RGBA", (N, N), (20, 0, 60, 0))
    shadow.putalpha(shape.filter(ImageFilter.GaussianBlur(N * 0.02)).point(lambda a: a * 0.45))
    base.alpha_composite(shadow, (0, round(N * 0.012)))

    tile = gradient(N).convert("RGBA")
    # 上半部的高光
    hl = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hl).ellipse((-N * 0.4, -N * 0.9, N * 1.4, N * 0.5), fill=46)
    tile = Image.composite(Image.new("RGBA", (N, N), (255, 255, 255, 255)), tile, hl.filter(ImageFilter.GaussianBlur(N * 0.14)))
    tile.putalpha(shape)
    base.alpha_composite(tile)

    # 白色符號＋淡淡的內陰影
    mark = glyph(N)
    glow = Image.new("RGBA", (N, N), (40, 0, 90, 0))
    glow.putalpha(ImageChops.multiply(mark.filter(ImageFilter.GaussianBlur(N * 0.015)), shape).point(lambda a: a * 0.5))
    base.alpha_composite(glow, (0, round(N * 0.01)))
    white = Image.new("RGBA", (N, N), (255, 255, 255, 0))
    white.putalpha(mark)
    base.alpha_composite(white)
    return base.resize((S, S), Image.LANCZOS)


def main():
    icon = build()
    icon.save(HERE / "icon.png")
    icon.resize((128, 128), Image.LANCZOS).save(HERE / "icon-128.png")  # App 啟動畫面用
    icon.save(HERE / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    icon.save(HERE / "icon.icns")
    print("已產生 icon.png / icon.ico / icon.icns")


if __name__ == "__main__":
    main()
