"""KOREA BITCOIN 로고 PNG 생성기 (한 번 실행해 assets/logo.png 를 만든다. 앱 실행에는 Pillow 불필요).

- 왼쪽: 태극 문양 (4배 슈퍼샘플링 후 축소 → 매끈한 가장자리)
- KOREA: 태극기 빨강/파랑 교차
- BITCOIN: 흰 글자 안에 건곤감리(☰☷☵☲) 막대 무늬
실행: python3 quant_floor/make_logo.py
"""
import math, os
from PIL import Image, ImageDraw, ImageFont

S = 4                      # 슈퍼샘플 배율
H = 54                     # 로고 높이(논리 px)
BG = (11, 12, 15, 0)       # 투명 배경
RED, BLUE, TBLUE = (205, 46, 58), (47, 107, 208), (0, 71, 160)
FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
OUT = os.path.join(os.path.dirname(__file__), "assets", "logo.png")


def taeguk(d, cx, cy, r):
    a = math.atan2(2, 3); ca, sa = math.cos(a), math.sin(a)
    rot = lambda px, py: (cx + (px - cx) * ca - (py - cy) * sa, cy + (px - cx) * sa + (py - cy) * ca)
    pts = [rot(cx + r * math.cos(math.pi * i / 180), cy - r * math.sin(math.pi * i / 180)) for i in range(181)]
    pts += [rot(cx - r / 2 + r / 2 * math.cos(math.pi + math.pi * i / 120), cy - r / 2 * math.sin(math.pi + math.pi * i / 120)) for i in range(121)]
    pts += [rot(cx + r / 2 + r / 2 * math.cos(math.pi - math.pi * i / 120), cy - r / 2 * math.sin(math.pi - math.pi * i / 120)) for i in range(121)]
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TBLUE)
    d.polygon(pts, fill=RED)


def trigram(d, cx, cy, pattern, ux, uy, L, t, g, color):
    """pattern: 1=이어진 막대, 0=끊어진 막대. (ux,uy)=막대에 수직인 방향."""
    wx, wy = -uy, ux
    def bar(px, py, length):
        d.polygon([(px - wx * length / 2 - ux * t / 2, py - wy * length / 2 - uy * t / 2),
                   (px + wx * length / 2 - ux * t / 2, py + wy * length / 2 - uy * t / 2),
                   (px + wx * length / 2 + ux * t / 2, py + wy * length / 2 + uy * t / 2),
                   (px - wx * length / 2 + ux * t / 2, py - wy * length / 2 + uy * t / 2)], fill=color)
    for k, solid in zip((-1, 0, 1), pattern):
        px, py = cx + ux * k * (t + g), cy + uy * k * (t + g)
        if solid:
            bar(px, py, L)
        else:
            seg = (L - g * 1.4) / 2; off = (seg + g * 1.4) / 2
            bar(px - wx * off, py - wy * off, seg); bar(px + wx * off, py + wy * off, seg)


def main():
    font = ImageFont.truetype(FONT, 38 * S)
    gap = 10 * S
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    wk = tmp.textlength("KOREA", font=font); wb = tmp.textlength("BITCOIN", font=font)
    x_text = 56 * S
    W = int(x_text + wk + gap + wb + 6 * S)
    img = Image.new("RGBA", (W, H * S), BG)
    d = ImageDraw.Draw(img)
    # 왼쪽 원형 엠블럼: assets/emblem.png (K₿TC 로고를 원으로 자른 것). 없으면 태극 문양.
    em_path = os.path.join(os.path.dirname(__file__), "assets", "emblem.png")
    if os.path.exists(em_path):
        em = Image.open(em_path).convert("RGBA").resize((int(46 * S), int(46 * S)), Image.LANCZOS)
        img.alpha_composite(em, (int(2 * S), int((H * S - em.height) / 2)))
    else:
        taeguk(d, 25 * S, H * S / 2, 22 * S)
    asc, desc = font.getmetrics()
    ty = (H * S - (asc - desc * 0.2)) / 2 - 1 * S
    x = x_text
    for ch, col in zip("KOREA", (RED, BLUE, RED, BLUE, RED)):
        d.text((x, ty), ch, font=font, fill=col)
        x += tmp.textlength(ch, font=font)
    # BITCOIN: 흰 바탕에 건곤감리 무늬를 깐 뒤 글자 모양으로 잘라낸다
    bx = x + gap
    tex = Image.new("RGBA", (int(wb) + 4 * S, H * S), (255, 255, 255, 255))
    td = ImageDraw.Draw(tex)
    n = math.hypot(3, 2)
    kinds = [((1, 1, 1), (3, 2)), ((0, 0, 0), (3, 2)), ((0, 1, 0), (3, -2)), ((1, 0, 1), (3, -2))]  # 건 곤 감 리
    lx = 0
    for i, ch in enumerate("BITCOIN"):
        w = tmp.textlength(ch, font=font)
        l, t_, r_, b_ = font.getbbox(ch)            # 실제 글자 윤곽
        gw, gh = r_ - l, b_ - t_
        pattern, (dx, dy) = kinds[i % 4]
        size = min(gw * 0.66, gh * 0.5)              # 글자 크기에 맞춤
        cx, cy = lx + (l + r_) / 2, ty + (t_ + b_) / 2
        trigram(td, cx, cy, pattern, dx / n, dy / n, L=size, t=size * 0.14, g=size * 0.14, color=(16, 16, 20, 255))
        lx += w
    mask = Image.new("L", tex.size, 0)
    ImageDraw.Draw(mask).text((0, ty), "BITCOIN", font=font, fill=255)
    img.paste(tex, (int(bx), 0), mask)
    img = img.resize((W // S, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print("saved", OUT, img.size)


if __name__ == "__main__":
    main()
