"""Assets de presentacion de la historia de NISAR: time-lapse 1920x1080 (ES y EN),
GIF para el README e imagen de portada para redes (1200x630), a partir de las
imagenes y de meta.json que deja nisar_productos.py. Tipografia Source Sans 3
del proyecto (se convierte de woff2 a ttf al vuelo). Salida en
frontend/nisar/datos/medios/.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import subprocess
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "frontend" / "nisar" / "datos"
MEDIOS = DATOS / "medios"
FUENTES = RAIZ / "frontend" / "vendor" / "fuentes"
LOGO = RAIZ / "frontend" / "logo.png"
FPS = 30
QUIETO, FUNDIDO = 0.9, 0.45
FONDO = (14, 17, 20)
TINTA, TINTA2, TINTA3 = (231, 233, 235), (163, 171, 177), (111, 120, 127)
CIAN, NARANJA, ACENTO = (34, 211, 238), (251, 146, 60), (120, 191, 220)
MESES = {"es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
         "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
TXT = {
    "es": {"marca": "EL OJO DE TLÁLOC · NISAR", "titulo": "El baile del agua",
           "sub": "Veracruz–Boca del Río · temporada de lluvias 2026",
           "pasada": "pasada {} de 10 · 05:49 h · banda L, 10 m",
           "lluvia": "Lluvia diaria (NASA POWER) y pasadas de NISAR", "humedad": "Índice de humedad del suelo",
           "leyenda": [("HH", (230, 90, 90), "ciudad, doble rebote"), ("HV", (120, 200, 90), "vegetación, volumen"),
                       ("oscuro", (40, 60, 80), "agua quieta")],
           "fuente": "NASA/JPL-Caltech · ISRO · ASF DAAC · NASA POWER"},
    "en": {"marca": "EL OJO DE TLÁLOC · NISAR", "titulo": "Water's dance",
           "sub": "Veracruz–Boca del Río, Mexico · 2026 rainy season",
           "pasada": "pass {} of 10 · 05:49 local · L-band, 10 m",
           "lluvia": "Daily rain (NASA POWER) and NISAR passes", "humedad": "Soil moisture index",
           "leyenda": [("HH", (230, 90, 90), "city, double bounce"), ("HV", (120, 200, 90), "vegetation, volume"),
                       ("dark", (40, 60, 80), "still water")],
           "fuente": "NASA/JPL-Caltech · ISRO · ASF DAAC · NASA POWER"},
}


def fuente(peso, tam):
    if not hasattr(fuente, "cache"):
        fuente.cache = {}
    if peso not in fuente.cache:
        tt = TTFont(FUENTES / "source-sans-3-{}.woff2".format(peso))
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        fuente.cache[peso] = buf.getvalue()
    return ImageFont.truetype(io.BytesIO(fuente.cache[peso]), tam)


def fecha_larga(iso, idioma):
    d = dt.date.fromisoformat(iso)
    if idioma == "es":
        return "{} {} {}".format(d.day, MESES["es"][d.month - 1], d.year)
    return "{} {}, {}".format(MESES["en"][d.month - 1], d.day, d.year)


def sobre_fondo(ruta, ancho, alto):
    img = Image.open(ruta).convert("RGBA")
    escala = min(ancho / img.width, alto / img.height)
    img = img.resize((round(img.width * escala), round(img.height * escala)), Image.LANCZOS)
    lienzo = Image.new("RGBA", (ancho, alto), FONDO + (255,))
    lienzo.alpha_composite(img, ((ancho - img.width) // 2, (alto - img.height) // 2))
    return lienzo


def grafica_lluvia(d, caja, meta, i_actual, idioma):
    x0, y0, x1, y1 = caja
    diaria = [x for x in meta["lluvia"]["diaria"] if "2026-06-15" <= x["fecha"] <= "2026-10-31"]
    tope = max(x["mm"] or 0 for x in diaria)
    n = len(diaria)
    paso = (x1 - x0) / n
    inicio = dt.date.fromisoformat(diaria[0]["fecha"])
    actual = meta["fechas"][i_actual]
    for k, x in enumerate(diaria):
        h = (x["mm"] or 0) / tope * (y1 - y0 - 18)
        color = ACENTO if x["fecha"] <= actual else (60, 70, 78)
        d.rectangle([x0 + k * paso, y1 - h, x0 + k * paso + max(paso - 1.2, 1), y1], fill=color)
    for j, f in enumerate(meta["fechas"]):
        k = (dt.date.fromisoformat(f) - inicio).days
        cx = x0 + k * paso + paso / 2
        r = 7 if j == i_actual else 4
        d.ellipse([cx - r, y1 + 12 - r, cx + r, y1 + 12 + r], fill=CIAN if j == i_actual else TINTA3)
    for mes in range(7, 11):
        k = (dt.date(2026, mes, 1) - inicio).days
        d.text((x0 + k * paso, y1 + 26), MESES[idioma][mes - 1], font=fuente(500, 20), fill=TINTA3)


def cuadro_fijo(meta, i, idioma, ancho=1920, alto=1080):
    t = TXT[idioma]
    lienzo = Image.new("RGBA", (ancho, alto), FONDO + (255,))
    d = ImageDraw.Draw(lienzo)
    logo = Image.open(LOGO).convert("RGBA").resize((64, 64), Image.LANCZOS)
    lienzo.alpha_composite(logo, (96, 86))
    d.text((176, 102), t["marca"], font=fuente(600, 24), fill=ACENTO)
    d.text((96, 190), t["titulo"], font=fuente(700, 92), fill=TINTA)
    d.text((100, 300), t["sub"], font=fuente(400, 32), fill=TINTA2)
    d.text((96, 400), fecha_larga(meta["fechas"][i], idioma), font=fuente(700, 76), fill=CIAN)
    d.text((100, 490), t["pasada"].format(i + 1), font=fuente(500, 26), fill=TINTA2)
    d.text((100, 580), t["lluvia"], font=fuente(600, 22), fill=TINTA2)
    grafica_lluvia(d, (100, 620, 860, 760), meta, i, idioma)
    hum = meta["humedad"]["indice_medio"][i]
    d.text((100, 850), t["humedad"], font=fuente(600, 22), fill=TINTA2)
    d.rounded_rectangle([100, 890, 760, 906], radius=8, fill=(43, 49, 54))
    d.rounded_rectangle([100, 890, 100 + 660 * hum, 906], radius=8, fill=(40, 150, 170))
    d.text((780, 878), "{:.2f}".format(hum), font=fuente(700, 32), fill=TINTA)
    x = 100
    for etiqueta, color, texto in t["leyenda"]:
        d.rounded_rectangle([x, 960, x + 18, 978], radius=4, fill=color)
        d.text((x + 28, 955), "{} · {}".format(etiqueta, texto), font=fuente(500, 21), fill=TINTA2)
        x += 28 + d.textlength("{} · {}".format(etiqueta, texto), font=fuente(500, 21)) + 34
    d.text((100, 1010), t["fuente"], font=fuente(400, 19), fill=TINTA3)
    return lienzo


def timelapse(meta, idioma, directorio):
    capas = meta["imagen"]["capas"]["rgb"]
    mapas = [sobre_fondo(DATOS / r, 980, 1080) for r in capas]
    fijos = [cuadro_fijo(meta, i, idioma) for i in range(len(capas))]
    n_quieto, n_fundido = round(QUIETO * FPS), round(FUNDIDO * FPS)
    k = 0
    for i in range(len(capas)):
        sig = (i + 1) % len(capas)
        for _ in range(n_quieto):
            cuadro = fijos[i].copy()
            cuadro.alpha_composite(mapas[i], (940, 0))
            cuadro.convert("RGB").save(directorio / "f{:05d}.png".format(k))
            k += 1
        for j in range(n_fundido):
            a = (j + 1) / (n_fundido + 1)
            a = a * a * (3 - 2 * a)
            cuadro = Image.blend(fijos[i], fijos[sig], a)
            cuadro.alpha_composite(Image.blend(mapas[i], mapas[sig], a), (940, 0))
            cuadro.convert("RGB").save(directorio / "f{:05d}.png".format(k))
            k += 1
    return k


def portada(meta, idioma):
    t = TXT[idioma]
    ancho, alto = 1200, 630
    mapa = Image.open(DATOS / meta["imagen"]["capas"]["rgb"][6]).convert("RGBA")
    mapa = mapa.crop((int(mapa.width * 0.25), int(mapa.height * 0.02), int(mapa.width * 0.985), int(mapa.height * 0.62)))
    escala = 860 / mapa.width
    mapa = mapa.resize((860, round(mapa.height * escala)), Image.LANCZOS)
    arriba = max(0, (mapa.height - alto) // 2)
    mapa = mapa.crop((0, arriba, 860, arriba + alto))
    lienzo = Image.new("RGBA", (ancho, alto), FONDO + (255,))
    lienzo.alpha_composite(mapa, (ancho - mapa.width, 0))
    alfa = Image.new("L", (ancho, alto))
    alfa.putdata([max(0, min(255, int(255 * (0.62 - x / ancho) / 0.22))) for _ in range(alto) for x in range(ancho)])
    sombra = Image.new("RGBA", (ancho, alto), FONDO + (255,))
    sombra.putalpha(alfa)
    lienzo.alpha_composite(sombra)
    d = ImageDraw.Draw(lienzo)
    logo = Image.open(LOGO).convert("RGBA").resize((52, 52), Image.LANCZOS)
    lienzo.alpha_composite(logo, (64, 70))
    d.text((128, 84), t["marca"], font=fuente(600, 21), fill=ACENTO)
    d.text((62, 170), t["titulo"], font=fuente(700, 86), fill=TINTA)
    d.text((66, 280), t["sub"], font=fuente(400, 28), fill=TINTA2)
    cifras = [("10", "pasadas" if idioma == "es" else "passes"), ("10 m", "píxel" if idioma == "es" else "pixel"),
              ("120", "días" if idioma == "es" else "days")]
    x = 66
    for valor, texto in cifras:
        d.text((x, 380), valor, font=fuente(700, 54), fill=CIAN)
        d.text((x, 446), texto, font=fuente(500, 22), fill=TINTA2)
        x += 170
    d.text((66, 560), t["fuente"], font=fuente(400, 18), fill=TINTA3)
    lienzo.convert("RGB").save(MEDIOS / "portada_{}.jpg".format(idioma), quality=90)


def main():
    MEDIOS.mkdir(parents=True, exist_ok=True)
    meta = json.loads((DATOS / "meta.json").read_text())
    for idioma in ("es", "en"):
        portada(meta, idioma)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            n = timelapse(meta, idioma, tmp)
            salida = MEDIOS / "timelapse_{}.mp4".format(idioma)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "slow",
                            "-movflags", "+faststart", str(salida)], check=True)
            if idioma == "es":
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(salida), "-vf",
                                "fps=8,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                                str(MEDIOS / "timelapse.gif")], check=True)
            print("{}: {} cuadros -> {}".format(idioma, n, salida.relative_to(RAIZ)))


if __name__ == "__main__":
    main()
