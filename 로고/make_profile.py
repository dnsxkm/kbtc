"""KBTC 텔레그램 프로필 이미지 생성기.
원 둘레(시계 방향, 12시 = 0°)에 건곤감리를 둥근 호로 배치:
  0~90° 감(☵) · 90~180° 곤(☷) · 180~270° 리(☲) · 270~360° 건(☰)
실행: python3 make_profile.py  →  KBTC_bot_profile_v2.png
"""
import sys, math
import os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "KBTC_desktop", "quant_floor"))
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import make_logo as ml

N, S = 640, 3
ALL_SOLID = False         # True 면 모든 막대를 이어서 그림 (괘 구분 없어짐)
NS = N * S
AV = "/System/Library/Fonts/Avenir Next.ttc"


def av(size, style):
    for i in range(20):
        try:
            f = ImageFont.truetype(AV, int(size), index=i)
        except OSError:
            break
        if style.lower() in " ".join(f.getname()).lower():
            return f
    return ImageFont.truetype(AV, int(size))


def radial(inner, outer, power=1.6):
    small = 320
    g = Image.new("L", (small, small)); px = g.load(); c = small / 2
    for y in range(small):
        for x in range(small):
            px[x, y] = int(255 * min(1, math.hypot(x - c, y - c) / c) ** power)
    g = g.resize((NS, NS), Image.BICUBIC)
    return Image.composite(Image.new("RGB", (NS, NS), outer), Image.new("RGB", (NS, NS), inner), g)


def trigram_ring(out, r_in, bar, gap, span, color):
    """시계 방향 각도(12시=0°) 기준으로 각 사분면 가운데에 괘를 호로 그린다."""
    layer = Image.new("RGBA", (NS, NS), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    c = NS / 2
    quads = {45: (0, 1, 0),    # 감
             135: (0, 0, 0),   # 곤
             225: (1, 0, 1),   # 리
             315: (1, 1, 1)}   # 건
    for center, pattern in quads.items():
        pil = center - 90                       # PIL: 3시=0°, 시계 방향
        for k, solid in enumerate(pattern):     # 안쪽 → 바깥쪽
            r = r_in + k * (bar + gap) + bar / 2
            box = (c - r, c - r, c + r, c + r)
            w = int(bar)
            if solid or ALL_SOLID:
                d.arc(box, pil - span / 2, pil + span / 2, fill=color, width=w)
            else:
                cut = 7
                d.arc(box, pil - span / 2, pil - cut / 2, fill=color, width=w)
                d.arc(box, pil + cut / 2, pil + span / 2, fill=color, width=w)
    return Image.alpha_composite(out, layer)


def build():
    tr = 0.33                                   # 태극 반지름 (둘레 괘 자리 확보)
    out = radial((26, 28, 34), (4, 4, 6)).convert("RGBA")
    tg = Image.new("RGBA", (NS, NS), (0, 0, 0, 0)); d = ImageDraw.Draw(tg)
    ml.RED, ml.TBLUE = (178, 28, 44), (0, 58, 140)
    ml.taeguk(d, NS / 2, NS / 2, NS * tr)
    shade = Image.new("L", (NS, NS)); sp = ImageDraw.Draw(shade)
    for i in range(60):
        t = i / 59
        sp.ellipse((NS * (0.05 + 0.25 * t), NS * (0.02 + 0.25 * t), NS * (0.75 + 0.25 * t), NS * (0.72 + 0.25 * t)), fill=int(255 * t))
    shade = shade.filter(ImageFilter.GaussianBlur(NS * 0.06))
    dark = Image.new("RGBA", (NS, NS), (0, 0, 0, 0)); dark.putalpha(shade.point(lambda v: int(v * 0.45)))
    tg = Image.alpha_composite(tg, Image.composite(dark, Image.new("RGBA", (NS, NS), (0, 0, 0, 0)), tg.split()[3]))
    glow = tg.split()[3].filter(ImageFilter.GaussianBlur(NS * 0.04))
    gl = Image.new("RGBA", (NS, NS), (190, 40, 60, 0)); gl.putalpha(glow.point(lambda v: int(v * 0.35)))
    out = Image.alpha_composite(out, gl)
    out = Image.alpha_composite(out, tg)
    ring = Image.new("RGBA", (NS, NS), (0, 0, 0, 0)); R = NS * (tr + 0.03)
    ImageDraw.Draw(ring).ellipse((NS / 2 - R, NS / 2 - R, NS / 2 + R, NS / 2 + R), outline=(255, 255, 255, 46), width=int(NS * 0.004))
    out = Image.alpha_composite(out, ring)
    # 둘레 건곤감리 (둥근 호)
    out = trigram_ring(out, r_in=NS * (tr + 0.058), bar=NS * 0.0095, gap=NS * 0.0085, span=85, color=(236, 236, 240, 225))
    # K₿TC (테두리 없음, 부드러운 그림자). Avenir 에 ₿ 글리프가 없어 B 에 세로 막대 2개를 더해 그린다.
    f = av(NS * 0.19, "Heavy"); txt = "KBTC"; track = NS * 0.011
    ws = [f.getlength(ch) for ch in txt]; total = sum(ws) + track * (len(txt) - 1)
    l, t, r, b = f.getbbox(txt); y = NS * 0.5 - (t + b) / 2
    sh = Image.new("RGBA", (NS, NS), (0, 0, 0, 0)); tx = Image.new("RGBA", (NS, NS), (0, 0, 0, 0))
    sd, td = ImageDraw.Draw(sh), ImageDraw.Draw(tx); x = (NS - total) / 2
    for i, (ch, w) in enumerate(zip(txt, ws)):
        for dr, dy, col in ((sd, NS * 0.012, (0, 0, 0, 170)), (td, 0, (255, 255, 255, 255))):
            dr.text((x, y + dy), ch, font=f, fill=col)
            if i == 1:  # ₿ 의 위아래 세로 막대
                gl, gt, gr, gb = f.getbbox("B")
                gw, gh = gr - gl, gb - gt
                bw, ext = gw * 0.11, gh * 0.13
                for fx in (0.30, 0.56):
                    bx = x + gl + gw * fx
                    dr.rectangle((bx, y + dy + gt - ext, bx + bw, y + dy + gt + gh * 0.1), fill=col)
                    dr.rectangle((bx, y + dy + gb - gh * 0.1, bx + bw, y + dy + gb + ext), fill=col)
        x += w + track
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(NS * 0.018)))
    out = Image.alpha_composite(out, tx)
    return out.convert("RGB").resize((N, N), Image.LANCZOS)


if __name__ == "__main__":
    img = build(); img.save(os.path.join(HERE, "KBTC_logo.png"))
    m = Image.new("L", (N, N), 0); ImageDraw.Draw(m).ellipse((0, 0, N, N), fill=255)
    pv = Image.new("RGB", (N + 200, N), (40, 40, 40)); pv.paste(img, (0, 0), m)
    pv.paste(img.resize((140, 140), Image.LANCZOS), (N + 40, 250), m.resize((140, 140)))
    pv.save(sys.argv[1] if len(sys.argv) > 1 else "profile_preview.png")
    print("saved 로고/KBTC_logo.png")
