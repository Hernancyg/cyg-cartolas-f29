"""
PDF "Planificación AT 2027 — Informe por analista" (18-09-2026, pedido
por el usuario: un resumen por cada analista seleccionado — completado/
en proceso/sin asignar, Caja/Banco — más el detalle de sus empresas,
pudiendo elegir uno o varios analistas a la vez).

Mismo enfoque que `app/global_igc/pdf_generator.py` (reportlab puro, sin
dependencias de sistema como Cairo/Pango, para desplegar sin problemas en
Render) — más simple porque el contenido es una lista de empresas por
analista, no un formulario de cálculo.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

NAVY = colors.HexColor("#0A1224")
NAVY_2 = colors.HexColor("#131B2E")
INDIGO = colors.HexColor("#2F6FED")
EMERALD = colors.HexColor("#0FA968")
AMBER = colors.HexColor("#C67C00")
DANGER = colors.HexColor("#D3222A")
BG = colors.HexColor("#F7F8FC")
BORDER = colors.HexColor("#E7E9F2")
TEXT_MUTED = colors.HexColor("#6B7383")
AVATAR_BG = colors.HexColor("#EDEFFF")

BRAND_ICON = Path(__file__).resolve().parent.parent / "static" / "img" / "brand-icon.png"

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

ESTADO_LABEL = {"completado": "Completado", "en_proceso": "En proceso", "sin_asignar": "Sin asignar"}
ESTADO_COLOR = {"completado": EMERALD, "en_proceso": INDIGO, "sin_asignar": DANGER}


def _fecha_larga(dt: datetime) -> str:
    return f"{dt.day} de {_MESES[dt.month - 1]} de {dt.year}"


class _Builder:
    MARGIN = 16 * mm
    PAGE_W, PAGE_H = A4
    ROW_H = 6.5 * mm

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
        c.drawRightString(self.x1, top - 9.5 * mm, "INFORME POR ANALISTA")
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8)
        c.drawRightString(self.x1, top - 14 * mm, f"Emitido el {_fecha_larga(datetime.now())}")

        self.y = top - 18 * mm
        c.setStrokeColor(BORDER)
        c.line(self.x0, self.y, self.x1, self.y)
        self.y -= 8 * mm

    def analista_header(self, analista, resumen):
        c = self.c
        self.asegurar_espacio(24 * mm)
        r = 5 * mm
        cx, cy = self.x0 + r, self.y - r
        c.setFillColor(AVATAR_BG)
        c.circle(cx, cy, r, fill=1, stroke=0)
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(cx, cy - 3, (analista[:1] or "?").upper())

        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.x0 + 2 * r + 4 * mm, self.y - 4 * mm, analista)
        total = resumen["total"]
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(
            self.x0 + 2 * r + 4 * mm, self.y - 8.5 * mm,
            f"{total} empresa{'s' if total != 1 else ''} asignada{'s' if total != 1 else ''}",
        )
        self.y -= (2 * r + 7 * mm)

        stats = [
            ("Completado", str(resumen["completado"]), EMERALD),
            ("En proceso", str(resumen["en_proceso"]), INDIGO),
            ("Sin asignar", str(resumen["sin_asignar"]), DANGER),
            ("Caja / Banco", f"{resumen['caja']} / {resumen['banco']}", NAVY_2),
        ]
        box_w = self.width / len(stats)
        for i, (label, valor, color) in enumerate(stats):
            bx = self.x0 + i * box_w
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 13)
            c.drawString(bx, self.y, valor)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica", 6.5)
            c.drawString(bx, self.y - 4 * mm, label.upper())
        self.y -= 10 * mm

    def tabla_empresas(self, filas):
        c = self.c
        col_empresa = self.x0
        col_prioridad = self.x0 + self.width * 0.48
        col_caja = self.x0 + self.width * 0.60
        col_avance = self.x0 + self.width * 0.76

        def encabezado():
            self.asegurar_espacio(self.ROW_H + 4 * mm)
            c.setFillColor(BG)
            c.rect(self.x0, self.y - 6 * mm, self.width, 6 * mm, fill=1, stroke=0)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(col_empresa + 2 * mm, self.y - 4 * mm, "EMPRESA")
            c.drawString(col_prioridad, self.y - 4 * mm, "PRIOR.")
            c.drawString(col_caja, self.y - 4 * mm, "CAJA/BANCO")
            c.drawString(col_avance, self.y - 4 * mm, "AVANCE")
            c.drawRightString(self.x1 - 2 * mm, self.y - 4 * mm, "ESTADO")
            self.y -= 6 * mm

        if not filas:
            self.asegurar_espacio(10 * mm)
            c.setFillColor(TEXT_MUTED)
            c.setFont("Helvetica-Oblique", 8.5)
            c.drawString(self.x0, self.y - 5 * mm, "Sin empresas asignadas.")
            self.y -= 10 * mm
            return

        encabezado()
        for f in filas:
            if self.y - (self.ROW_H + 2 * mm) < self.MARGIN:
                self.nueva_pagina()
                encabezado()
            c.setStrokeColor(BORDER)
            c.line(self.x0, self.y, self.x1, self.y)
            base_y = self.y - self.ROW_H + 2 * mm
            c.setFillColor(NAVY_2)
            c.setFont("Helvetica", 8)
            c.drawString(col_empresa + 2 * mm, base_y, (f.get("empresa") or "")[:52])
            c.drawString(col_prioridad, base_y, str(f.get("prioridad")) if f.get("prioridad") else "—")
            c.drawString(col_caja, base_y, f.get("caja_banco") or "—")
            c.drawString(col_avance, base_y, f.get("actualizacion_balance") or "—")
            estado = f.get("estado") or "sin_asignar"
            c.setFillColor(ESTADO_COLOR.get(estado, TEXT_MUTED))
            c.setFont("Helvetica-Bold", 7.5)
            c.drawRightString(self.x1 - 2 * mm, base_y, ESTADO_LABEL.get(estado, estado))
            self.y -= self.ROW_H
        self.y -= 8 * mm


def generar_pdf_informe(secciones) -> BytesIO:
    """`secciones`: lista de dicts `{analista, filas, resumen}` — `filas`
    son las filas de `planificacion_at2027_repo.listar_todos()` (con
    `estado` ya calculado) de ESE analista, `resumen` el dict que arma
    `app/planificacion_at2027/routes.py:_resumen_de` sobre esas mismas
    filas. Devuelve un BytesIO listo para `send_file`."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    b = _Builder(c)
    b.header()
    for i, seccion in enumerate(secciones):
        if i > 0:
            b.asegurar_espacio(10 * mm)
            c.setStrokeColor(BORDER)
            c.line(b.x0, b.y, b.x1, b.y)
            b.y -= 8 * mm
        b.analista_header(seccion["analista"], seccion["resumen"])
        b.tabla_empresas(seccion["filas"])
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
