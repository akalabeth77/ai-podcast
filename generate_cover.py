"""Generuje cover art pre Kolby AI Podcast (1400x1400 px)."""
from PIL import Image, ImageDraw, ImageFont
import math

SIZE = 1400

img = Image.new("RGB", (SIZE, SIZE), "#0a0a1a")
draw = ImageDraw.Draw(img)

# Gradient background – tmavá modrá až fialová
for y in range(SIZE):
    t = y / SIZE
    r = int(10 + 30 * t)
    g = int(10 + 5 * t)
    b = int(26 + 60 * t)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

# Sieťový vzor (AI brain grid)
grid_color = (40, 60, 120, 80)
for x in range(0, SIZE, 70):
    draw.line([(x, 0), (x, SIZE)], fill=(30, 50, 100), width=1)
for y in range(0, SIZE, 70):
    draw.line([(0, y), (SIZE, y)], fill=(30, 50, 100), width=1)

# Kruhové "vlny" v strede
cx, cy = SIZE // 2, SIZE // 2
for r in range(80, 500, 60):
    alpha = max(20, 80 - r // 8)
    draw.ellipse([(cx - r, cy - r - 100), (cx + r, cy + r - 100)],
                 outline=(80, 120, 220, alpha), width=2)

# Centrálny glowing kruh
for offset in range(60, 0, -10):
    a = int(15 + (60 - offset) * 2)
    draw.ellipse([(cx - offset, cy - offset - 100), (cx + offset, cy + offset - 100)],
                 fill=(100, 160, 255, a))
draw.ellipse([(cx - 40, cy - 140), (cx + 40, cy - 60)],
             fill=(180, 210, 255))

# Texty – pokús sa načítať systémový font, inak default
try:
    font_title = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 110)
    font_sub = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 52)
    font_tag = ImageFont.truetype("C:/Windows/Fonts/ariali.ttf", 38)
except Exception:
    font_title = ImageFont.load_default()
    font_sub = font_title
    font_tag = font_title

# KOLBY
text1 = "KOLBY"
bbox = draw.textbbox((0, 0), text1, font=font_title)
w = bbox[2] - bbox[0]
draw.text(((SIZE - w) // 2, 680), text1, font=font_title, fill=(255, 255, 255))

# AI Podcast
text2 = "AI PODCAST"
bbox2 = draw.textbbox((0, 0), text2, font=font_title)
w2 = bbox2[2] - bbox2[0]
draw.text(((SIZE - w2) // 2, 820), text2, font=font_title, fill=(120, 180, 255))

# Podtitul
text3 = "Každý deň novinky zo sveta umelej inteligencie"
bbox3 = draw.textbbox((0, 0), text3, font=font_sub)
w3 = bbox3[2] - bbox3[0]
draw.text(((SIZE - w3) // 2, 1000), text3, font=font_sub, fill=(160, 190, 240))

# Dekoratívna linka
draw.rectangle([(cx - 200, 1070), (cx + 200, 1073)], fill=(100, 150, 255))

# Jazyk
text4 = "🇸🇰 po slovensky"
try:
    font_flag = ImageFont.truetype("C:/Windows/Fonts/seguiemj.ttf", 36)
except Exception:
    font_flag = font_tag
bbox4 = draw.textbbox((0, 0), text4, font=font_flag)
w4 = bbox4[2] - bbox4[0]
draw.text(((SIZE - w4) // 2, 1090), text4, font=font_flag, fill=(200, 220, 255))

out = "docs/cover.png"
img.save(out, "PNG", optimize=True)
print(f"Cover uložený: {out} ({SIZE}x{SIZE}px)")
