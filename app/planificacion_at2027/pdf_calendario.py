"""
PDF "Planificación AT 2027 — Calendario de Reuniones" (22-09-2026,
pedido por el usuario: una vista de calendario, por analista, con las
empresas que tienen reunión programada en cada mes del ciclo).

Toma las 4 columnas de reunión que ya tiene cada empresa en
`planificacion_at2027_repo` (`reunion_cat1_1`, `reunion_cat2`,
`reunion_cat3`, `reunion_cat1_2` — cada una guarda el NOMBRE DEL MES en
que le toca esa reunión, no una fecha) y arma, por analista, un
calendario de 2 filas x 3 meses (Septiembre-Octubre-Noviembre /
Diciembre-Enero-Febrero) con las empresas que tienen reunión ese mes —
una empresa puede aparecer en el mismo mes con más de una categoría
(ej. Cat.1 1ª vez y Cat.2 caen el mismo mes).

Mismo enfoque que `pdf_informe.py` (reportlab puro, propia clase
`_Builder` en vez de una base compartida — incluso `pdf_informe.py`
sigue el mismo criterio con `global_igc/pdf_generator.py`, cada informe
con su propio dibujo de encabezado). Hoja apaisada (a diferencia del
informe por analista, que es vertical) porque 3 meses uno al lado del
otro necesitan más ancho.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

NAVY = colors.HexColor("#0A1224")
NAVY_2 = colors.HexColor("#131B2E")
INDIGO = colors.HexColor("#2F6FED")
TEAL = colors.HexColor("#0E9488")
AMBER = colors.HexColor("#C67C00")
DANGER = colors.HexColor("#D3222A")
BG = colors.HexColor("#F7F8FC")
BORDER = colors.HexColor("#E7E9F2")
TEXT_MUTED = colors.HexColor("#6B7383")
AVATAR_BG = colors.HexColor("#EDEFFF")
CHIP_BG = colors.HexColor("#FAFBFE")

BRAND_ICON = Path(__file__).resolve().parent.parent / "static" / "img" / "brand-icon.png"

MESES = ["Septiembre", "Octubre", "Noviembre", "Diciembre", "Enero", "Febrero"]

# Mismo orden en que se ven las 4 columnas de reunión en la tabla real
# (izquierda a derecha: Cat1 1ª vez, Cat2, Cat3, Cat1 2ª vez).
CATS = ["reunion_cat1_1", "reunion_cat2", "reunion_cat3", "reunion_cat1_2"]
CAT_LABEL = {"reunion_cat1_1": "1ª", "reunion_cat2": "2", "reunion_cat3": "3", "reunion_cat1_2": "1ª·2"}
CAT_COLOR = {"reunion_cat1_1": INDIGO, "reunion_cat2": AMBER, "reunion_cat3": DANGER, "reunion_cat1_2": TEAL}
CAT_LEYENDA = {
    "reunion_cat1_1": "Cat. 1 (1ª vez)", "reunion_cat2": "Cat. 2",
    "reunion_cat3": "Cat. 3", "reunion_cat1_2": "Cat. 1 (2ª vez)",
}

_MESES_LARGO = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_larga(dt: datetime) -> str:
    return f"{dt.day} de {_MESES_LARGO[dt.month - 1]} de {dt.year}"


def _envolver(c, texto, ancho_max, fuente, tam):
    """Corta `texto` en líneas que quepan en `ancho_max` puntos, usando el
    ancho real de la fuente (mismo criterio manual que ya usa
    pdf_informe.py, sin Platypus/Paragraph)."""
    palabras = texto.split(" ")
    lineas, actual = [], ""
    for p in palabras:
        candidato = (actual + " " + p).strip()
        if c.stringWidth(candidato, fuente, tam) <= ancho_max or not actual:
            actual = candidato
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


class _Builder:
    MARGIN = 14 * mm
    PAGE_W, PAGE_H = landscape(A4)

    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.width = self.PAGE_W - 2 * self.MARGIN
        self.x0 = self.MARGIN
        self.x1 = self.PAGE_W - self.MARGIN
        self.y = self.PAGE_H - self.MARGIN

    def nueva_pagina(self):
        self.c.showPage()
        self.y = self.PAGE_H - self.MARGIN

    def asegurar_espacio(self, alto):
        if self.y - alto < self.MARGIN:
            self.nueva_pagina()

    def header(self):
        c = self.c
        top = self.y
        icon_size = 10 * mm
        if BRAND_ICON.exists():
            try:
                c.setFillColor(NAVY)
                c.roundRect(self.x0, top - icon_size, icon_size, icon_size, 2 * mm, fill=1, stroke=0)
                pad = 1.6 * mm
                c.drawImage(
                    str(BRAND_ICON), self.x0 + pad, top - icon_size + pad,
                    width=icon_size - 2 * pad, height=icon_size - 2 * pad,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception:
                pass
        tx = self.x0 + icon_size + 3 * mm
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(tx, top - 5 * mm, "C&G Group")
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(tx, top - 9 * mm, "CONSULTORES Y ABOGADOS")

        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(self.x1, top - 5 * mm, "PLANIFICACIÓN AT 2027")
        c.setFillColor(INDIGO)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(self.x1, top - 9.5 * mm, "CALENDARIO DE REUNIONES")
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8)
        c.drawRightString(self.x1, top - 14 * mm, f"Emitido el {_fecha_larga(datetime.now())}")

        self.y = top - 18 * mm
        c.setStrokeColor(BORDER)
        c.line(self.x0, self.y, self.x1, self.y)
        self.y -= 6 * mm

        c.setFont("Helvetica", 7)
        c.setFillColor(TEXT_MUTED)
        lx = self.x0
        c.drawString(lx, self.y - 3.2 * mm, "Categoría:")
        lx += 16 * mm
        for cat in CATS:
            r = 1.6 * mm
            c.setFillColor(CAT_COLOR[cat])
            c.circle(lx, self.y - 3 * mm, r, fill=1, stroke=0)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica", 7)
            label = CAT_LEYENDA[cat]
            c.drawString(lx + 3 * mm, self.y - 3.9 * mm, label)
            lx += 3 * mm + c.stringWidth(label, "Helvetica", 7) + 8 * mm
        self.y -= 10 * mm

    def analista_header(self, nombre, n_empresas, n_reuniones):
        c = self.c
        self.asegurar_espacio(16 * mm)
        r = 4.5 * mm
        cx, cy = self.x0 + r, self.y - r
        c.setFillColor(AVATAR_BG)
        c.circle(cx, cy, r, fill=1, stroke=0)
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, cy - 3, (nombre[:1] or "?").upper())

        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.x0 + 2 * r + 4 * mm, self.y - 3.6 * mm, nombre)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawString(
            self.x0 + 2 * r + 4 * mm, self.y - 7.6 * mm,
            f"{n_empresas} empresa{'s' if n_empresas != 1 else ''} con reunión · "
            f"{n_reuniones} reunion{'es' if n_reuniones != 1 else ''} en el ciclo",
        )
        self.y -= (2 * r + 6 * mm)

    def calendario(self, filas):
        """`filas`: filas de `planificacion_at2027_repo.listar_todos()` de
        UN analista (con `empresa` y las 4 columnas de reunión)."""
        por_mes = {}
        for mes in MESES:
            lista = []
            for f in filas:
                tags = [cat for cat in CATS if (f.get(cat) or "").strip() == mes]
                if tags:
                    lista.append(((f.get("empresa") or "").strip(), tags))
            por_mes[mes] = lista

        self._fila_calendario(MESES[:3], por_mes)
        self.y -= 4 * mm
        self._fila_calendario(MESES[3:], por_mes)
        self.y -= 6 * mm

    def _fila_calendario(self, meses_fila, por_mes):
        c = self.c
        col_gap = 3 * mm
        col_w = (self.width - col_gap * 2) / 3
        header_h = 8 * mm
        pad = 3 * mm
        fuente, tam, interlinea = "Helvetica", 8, 3.6 * mm
        chip_pad_v = 1.8 * mm
        tag_fila_h = 4.8 * mm
        ancho_nombre = col_w - 2 * pad

        alturas = []
        for mes in meses_fila:
            lista = por_mes[mes]
            if not lista:
                alturas.append(header_h + 11 * mm)
                continue
            h = header_h + pad
            for nombre, tags in lista:
                lineas = _envolver(c, nombre, ancho_nombre, fuente, tam)
                h += len(lineas) * interlinea + tag_fila_h + chip_pad_v * 2 + 1.6 * mm
            alturas.append(h + pad)
        alto_fila = max(alturas)

        self.asegurar_espacio(alto_fila + 4 * mm)
        top = self.y
        for i, mes in enumerate(meses_fila):
            bx = self.x0 + i * (col_w + col_gap)
            lista = por_mes[mes]
            n = len(lista)

            c.setFillColor(colors.white if lista else BG)
            c.setStrokeColor(BORDER)
            c.roundRect(bx, top - alto_fila, col_w, alto_fila, 2 * mm, fill=1, stroke=1)
            c.setFillColor(NAVY_2 if lista else TEXT_MUTED)
            c.roundRect(bx, top - header_h, col_w, header_h, 2 * mm, fill=1, stroke=0)
            c.rect(bx, top - header_h, col_w, header_h / 2, fill=1, stroke=0)  # cuadra las esquinas de abajo del rótulo
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(bx + pad, top - header_h / 2 - 1.6 * mm, mes.upper())
            if n:
                c.setFont("Helvetica", 7)
                c.drawRightString(bx + col_w - pad, top - header_h / 2 - 1.4 * mm, f"{n} empresa{'s' if n != 1 else ''}")

            cy = top - header_h - pad
            if not lista:
                c.setFillColor(TEXT_MUTED)
                c.setFont("Helvetica-Oblique", 8)
                c.drawString(bx + pad, cy - 4.5 * mm, "Sin reuniones")
            for nombre, tags in lista:
                lineas = _envolver(c, nombre, ancho_nombre, fuente, tam)
                chip_h = len(lineas) * interlinea + tag_fila_h + chip_pad_v * 2
                c.setFillColor(CHIP_BG)
                c.roundRect(bx + pad - 1.2 * mm, cy - chip_h, col_w - 2 * pad + 2.4 * mm, chip_h, 1.4 * mm, fill=1, stroke=0)
                ty = cy - chip_pad_v - 2.8 * mm
                c.setFillColor(NAVY_2)
                c.setFont(fuente, tam)
                for linea in lineas:
                    c.drawString(bx + pad, ty, linea)
                    ty -= interlinea
                # Las categorías van en su propia fila bajo el nombre (no al
                # lado): un nombre de 2 líneas con 2+ categorías chocaba con
                # el texto cuando se intentaba compartir la primera línea.
                tagx = bx + pad
                tagy = ty - tag_fila_h + 1.3 * mm
                for tag in tags:
                    label = CAT_LABEL[tag]
                    w = c.stringWidth(label, "Helvetica-Bold", 6.5) + 2.4 * mm
                    c.setFillColor(CAT_COLOR[tag])
                    c.roundRect(tagx, tagy, w, 3.8 * mm, 1 * mm, fill=1, stroke=0)
                    c.setFillColor(colors.white)
                    c.setFont("Helvetica-Bold", 6.5)
                    c.drawCentredString(tagx + w / 2, tagy + 1.2 * mm, label)
                    tagx += w + 1.2 * mm
                cy -= chip_h + 1.6 * mm
        self.y = top - alto_fila


def generar_pdf_calendario(secciones) -> BytesIO:
    """`secciones`: lista de dicts `{analista, filas}` — `filas` son las
    filas de `planificacion_at2027_repo.listar_todos()` de ESE analista
    (no hace falta `estado`/`resumen`, este PDF no los muestra). Devuelve
    un BytesIO listo para `send_file`."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    b = _Builder(c)
    b.header()
    for i, seccion in enumerate(secciones):
        if i > 0:
            b.asegurar_espacio(10 * mm)
            c.setStrokeColor(BORDER)
            c.line(b.x0, b.y, b.x1, b.y)
            b.y -= 8 * mm
        filas = seccion["filas"]
        n_empresas = sum(1 for f in filas if any((f.get(cat) or "").strip() for cat in CATS))
        n_reuniones = sum(1 for f in filas for cat in CATS if (f.get(cat) or "").strip())
        b.analista_header(seccion["analista"], n_empresas, n_reuniones)
        b.calendario(filas)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
