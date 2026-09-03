"""
Generación del PDF "Global Complementario · Resumido", pedido por el
usuario el 03-09-2026 a partir de un mockup de referencia (C&G Group).

Reproduce la estructura del mockup (encabezado con marca + título, datos
del contribuyente, resumen de rentas, cálculo de base imponible, detalle
de créditos, resultado de impuestos y nota final), con dos diferencias
explícitas pedidas por el usuario:

  - Se omiten del mockup: dirección/comuna del contribuyente, firma con
    nombre de una persona, y el teléfono/barra de contacto del pie de
    página — el usuario pidió dejar solo la nota final, sin firma ni
    contacto.
  - Las filas de "Resumen de Rentas" NO son las 5 genéricas del mockup
    (Dividendos/Sueldos/Arriendos/Honorarios/Otros) sino las categorías
    reales de esta calculadora (Sueldos, Honorarios, Retiros 14A, Retiros
    14D3, Arriendos, Intereses y Reajustes, Ganancias de Capital, Otros
    Ingresos) — la calculadora ya no tiene un campo "Dividendos" (se quitó
    en una corrección anterior) y separa los retiros por régimen.

Usa reportlab (pura Python, sin dependencias de sistema como Cairo/Pango)
para poder desplegar sin problemas en Render.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

NAVY = colors.HexColor("#0E1E3A")
NAVY_2 = colors.HexColor("#16233F")
BLUE = colors.HexColor("#2F6FED")
BG = colors.HexColor("#F4F6FA")
BORDER = colors.HexColor("#E3E7EE")
TEXT_MUTED = colors.HexColor("#5B6472")
GREEN = colors.HexColor("#1E8E5A")
ORANGE = colors.HexColor("#C4590A")

BRAND_ICON = Path(__file__).resolve().parent.parent / "static" / "img" / "brand-icon.png"

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_larga(dt: datetime) -> str:
    return f"{dt.day} de {_MESES[dt.month - 1]} de {dt.year}"


def _clp(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    sign = "-" if n < 0 else ""
    return sign + "$" + "{:,.0f}".format(abs(n)).replace(",", ".")


class _PdfBuilder:
    """Dibuja el resumen sobre un canvas de reportlab, página A4, avanzando
    un cursor vertical `self.y` a medida que agrega secciones."""

    MARGIN = 18 * mm
    PAGE_W, PAGE_H = A4

    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.width = self.PAGE_W - 2 * self.MARGIN
        self.x0 = self.MARGIN
        self.x1 = self.PAGE_W - self.MARGIN
        self.y = self.PAGE_H - self.MARGIN

    # -- primitivas ---------------------------------------------------
    def section_bar(self, titulo: str, h=8 * mm):
        c = self.c
        c.setFillColor(NAVY)
        c.rect(self.x0, self.y - h, self.width, h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(self.x0 + 3 * mm, self.y - h + 2.6 * mm, titulo)
        self.y -= h

    def box_frame(self, h, fill=colors.white):
        c = self.c
        c.setFillColor(fill)
        c.setStrokeColor(BORDER)
        c.rect(self.x0, self.y - h, self.width, h, fill=1, stroke=1)

    def line_row(self, label, value, y, bold=False, color=NAVY_2, size=9.5, indent=4 * mm):
        c = self.c
        c.setFillColor(TEXT_MUTED if not bold else color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(self.x0 + indent, y, label)
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawRightString(self.x1 - indent, y, value)

    def gap(self, h):
        self.y -= h

    # -- secciones ------------------------------------------------------
    def header(self, entrada):
        c = self.c
        top = self.y

        # Marca (izquierda). El ícono (app/static/img/brand-icon.png) es
        # blanco sobre fondo transparente — pensado para la barra lateral
        # navy de la app — así que necesita un fondo oscuro detrás para
        # verse en el PDF (blanco), igual que en el sidebar.
        icon_size = 11 * mm
        if BRAND_ICON.exists():
            try:
                c.setFillColor(NAVY)
                c.roundRect(self.x0, top - icon_size, icon_size, icon_size, 2 * mm, fill=1, stroke=0)
                pad = 1.8 * mm
                c.drawImage(
                    str(BRAND_ICON), self.x0 + pad, top - icon_size + pad,
                    width=icon_size - 2 * pad, height=icon_size - 2 * pad,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception:
                pass
        tx = self.x0 + icon_size + 3 * mm
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(tx, top - 5 * mm, "C&G Group")
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(tx, top - 9 * mm, "CONSULTORES Y ABOGADOS")
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(tx, top - 12.5 * mm, "¿Emprendemos?")

        # Título (derecha)
        anio = int(getattr(entrada, "anio_tributario", 2026) or 2026)
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 15)
        c.drawRightString(self.x1, top - 5 * mm, "GLOBAL COMPLEMENTARIO")
        c.setFont("Helvetica-Bold", 9.5)
        c.setFillColor(BLUE)
        c.drawRightString(self.x1, top - 9.5 * mm, "RESUMIDO")
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica", 9)
        c.drawRightString(self.x1, top - 14 * mm, f"AÑO TRIBUTARIO {anio}")
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8)
        c.drawRightString(self.x1, top - 18 * mm, f"Fecha de emisión: {_fecha_larga(datetime.now())}")

        self.y = top - 22 * mm
        c.setStrokeColor(BORDER)
        c.line(self.x0, self.y, self.x1, self.y)
        self.gap(6 * mm)

    def datos_contribuyente(self, entrada):
        self.section_bar("DATOS DEL CONTRIBUYENTE")
        h = 16 * mm
        self.box_frame(h)
        c = self.c
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(self.x0 + 4 * mm, self.y - 6 * mm, "Nombre")
        c.drawString(self.x0 + 4 * mm, self.y - 12 * mm, "RUT")
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica", 9.5)
        c.drawString(self.x0 + 28 * mm, self.y - 6 * mm, f": {entrada.nombre_contribuyente or '—'}")
        c.drawString(self.x0 + 28 * mm, self.y - 12 * mm, f": {entrada.rut_contribuyente or '—'}")
        self.y -= h
        self.gap(6 * mm)

    def resumen_rentas(self, entrada, r):
        filas = []
        if entrada.retiros_14a or entrada.credito_retiros_14a:
            filas.append((
                "Retiros 14 A",
                entrada.retiros_14a + entrada.credito_retiros_14a,
                entrada.credito_retiros_14a,
            ))
        if entrada.retiros_14d3 or entrada.credito_retiros_14d3:
            filas.append((
                "Retiros 14 D N°3",
                entrada.retiros_14d3 + entrada.credito_retiros_14d3,
                entrada.credito_retiros_14d3,
            ))
        if r.renta_neta_sueldos or entrada.credito_iusc:
            filas.append(("Sueldos", r.renta_neta_sueldos, entrada.credito_iusc))
        if r.honorarios_tributables or entrada.credito_honorarios:
            filas.append(("Honorarios", r.honorarios_tributables, entrada.credito_honorarios))
        if entrada.arriendos_netos or entrada.credito_arriendos:
            filas.append(("Arriendos", entrada.arriendos_netos, entrada.credito_arriendos))
        if entrada.intereses_reajustes:
            filas.append(("Intereses y Reajustes", entrada.intereses_reajustes, 0))
        if entrada.ganancias_capital:
            filas.append(("Ganancias de Capital", entrada.ganancias_capital, 0))
        if entrada.otros_ingresos_afectos:
            filas.append(("Otros Ingresos Afectos", entrada.otros_ingresos_afectos, 0))
        if entrada.otros_creditos:
            filas.append(("Otros Créditos (sin renta asociada)", 0, entrada.otros_creditos))

        self.section_bar("RESUMEN DE RENTAS")
        row_h = 8 * mm
        header_h = 7 * mm
        h = header_h + row_h * len(filas) + row_h  # + fila de totales

        self.box_frame(h)
        c = self.c
        col_num_x = self.x0 + 4 * mm
        col_tipo_x = self.x0 + 10 * mm
        col_monto_x = self.x0 + self.width * 0.68
        col_credito_x = self.x1 - 4 * mm

        # encabezado de la tabla
        c.setFillColor(BG)
        c.rect(self.x0, self.y - header_h, self.width, header_h, fill=1, stroke=0)
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(col_tipo_x, self.y - header_h + 2.3 * mm, "TIPO DE RENTA")
        c.drawRightString(col_monto_x, self.y - header_h + 2.3 * mm, "MONTO ($)")
        c.drawRightString(col_credito_x, self.y - header_h + 2.3 * mm, "CRÉDITO ($)")
        y = self.y - header_h

        for i, (label, monto, credito) in enumerate(filas, start=1):
            y -= row_h
            c.setStrokeColor(BORDER)
            c.line(self.x0, y, self.x1, y)
            # círculo numerado
            cx, cy = col_num_x + 2 * mm, y + row_h / 2 - 1.1 * mm
            c.setFillColor(BLUE)
            c.circle(cx, cy, 3 * mm, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(cx, cy - 1.1 * mm, str(i))
            c.setFillColor(NAVY_2)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(col_tipo_x + 8 * mm, y + row_h / 2 - 1.4 * mm, label.upper())
            c.setFont("Helvetica", 9.5)
            c.drawRightString(col_monto_x, y + row_h / 2 - 1.4 * mm, _clp(monto) if monto else "—")
            c.drawRightString(col_credito_x, y + row_h / 2 - 1.4 * mm, _clp(credito) if credito else "—")

        # fila de totales
        y -= row_h
        c.setFillColor(BG)
        c.rect(self.x0, y, self.width, row_h, fill=1, stroke=0)
        total_monto = r.renta_bruta_retiros + r.otras_rentas_afectas
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(col_tipo_x, y + row_h / 2 - 1.4 * mm, "TOTAL RENTAS")
        c.drawRightString(col_monto_x, y + row_h / 2 - 1.4 * mm, _clp(total_monto))
        c.drawRightString(col_credito_x, y + row_h / 2 - 1.4 * mm, _clp(r.total_creditos))

        self.y -= h
        self.gap(6 * mm)

    def dos_columnas(self, r):
        """'Cálculo de Base Imponible' (izq.) + 'Detalle de Créditos' (der.)."""
        creditos = [
            ("Crédito IDPC Retiros 14 A/14 D N°3", r.total_creditos_idpc),
            ("Crédito IUSC (sueldos)", r.detalle_creditos.get("credito_iusc", 0)),
            ("Crédito por Honorarios", r.detalle_creditos.get("credito_honorarios", 0)),
            ("Crédito por Arriendos", r.detalle_creditos.get("credito_arriendos", 0)),
            ("Otros Créditos", r.detalle_creditos.get("otros_creditos", 0)),
        ]
        creditos = [(label, monto) for label, monto in creditos if monto]

        col_w = (self.width - 6 * mm) / 2
        left_x0, right_x0 = self.x0, self.x0 + col_w + 6 * mm

        n_lineas_izq = 3
        n_lineas_der = max(len(creditos), 1) + 1
        bar_h = 8 * mm
        line_h = 7.5 * mm
        h_izq = n_lineas_izq * line_h + 4 * mm
        h_der = n_lineas_der * line_h + 4 * mm
        body_h = max(h_izq, h_der)

        c = self.c
        top = self.y

        # barras de título
        c.setFillColor(NAVY)
        c.rect(left_x0, top - bar_h, col_w, bar_h, fill=1, stroke=0)
        c.rect(right_x0, top - bar_h, col_w, bar_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(left_x0 + 3 * mm, top - bar_h + 2.6 * mm, "CÁLCULO DE BASE IMPONIBLE")
        c.drawString(right_x0 + 3 * mm, top - bar_h + 2.6 * mm, "DETALLE DE CRÉDITOS")

        y0 = top - bar_h
        c.setFillColor(colors.white)
        c.setStrokeColor(BORDER)
        c.rect(left_x0, y0 - body_h, col_w, body_h, fill=1, stroke=1)
        c.rect(right_x0, y0 - body_h, col_w, body_h, fill=1, stroke=1)

        # columna izquierda
        yy = y0 - 6 * mm
        total_rentas = r.renta_bruta_retiros + r.otras_rentas_afectas
        self._kv(left_x0, col_w, yy, "Total Rentas", _clp(total_rentas))
        yy -= line_h
        self._kv(left_x0, col_w, yy, "Menos: Rebajas (Pensiones Alimenticias)", f"({_clp(r.total_rebajas)})")
        yy -= line_h + 1.5 * mm
        c.setStrokeColor(BORDER)
        c.line(left_x0 + 3 * mm, yy + 4 * mm, left_x0 + col_w - 3 * mm, yy + 4 * mm)
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(left_x0 + 3 * mm, yy - 1 * mm, "BASE IMPONIBLE ANUAL")
        c.drawRightString(left_x0 + col_w - 3 * mm, yy - 1 * mm, _clp(r.base_imponible))

        # columna derecha
        yy = y0 - 6 * mm
        if creditos:
            for label, monto in creditos:
                self._kv(right_x0, col_w, yy, label, _clp(monto))
                yy -= line_h
        else:
            self._kv(right_x0, col_w, yy, "Sin créditos ingresados", "—")
            yy -= line_h
        yy -= 1.5 * mm
        c.setStrokeColor(BORDER)
        c.line(right_x0 + 3 * mm, yy + 4 * mm, right_x0 + col_w - 3 * mm, yy + 4 * mm)
        c.setFillColor(BLUE)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(right_x0 + 3 * mm, yy - 1 * mm, "TOTAL CRÉDITOS")
        c.drawRightString(right_x0 + col_w - 3 * mm, yy - 1 * mm, _clp(r.total_creditos))

        self.y = y0 - body_h
        self.gap(6 * mm)

    def _kv(self, x0, w, y, label, value):
        c = self.c
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8.5)
        c.drawString(x0 + 3 * mm, y, label)
        c.setFillColor(NAVY_2)
        c.setFont("Helvetica", 8.5)
        c.drawRightString(x0 + w - 3 * mm, y, value)

    def resultado_impuestos(self, r):
        self.section_bar("RESULTADO DE IMPUESTOS")

        cajas = [("IMPUESTO DETERMINADO", r.impuesto_determinado, None)]
        cajas.append(("TOTAL CRÉDITOS", r.total_creditos, "−"))
        if r.pago_cotizacion_honorarios:
            cajas.append(("COTIZACIÓN PREV. HONORARIOS", r.pago_cotizacion_honorarios, "+"))
        etiqueta_final = "IMPUESTO A PAGAR" if r.a_pagar else "SALDO A FAVOR"
        cajas.append((etiqueta_final, abs(r.resultado), "="))

        n = len(cajas)
        h = 22 * mm
        gap = 3 * mm
        box_w = (self.width - gap * (n - 1)) / n
        c = self.c
        top = self.y

        for i, (label, valor, op) in enumerate(cajas):
            bx = self.x0 + i * (box_w + gap)
            es_final = i == n - 1
            fill = (GREEN if r.a_pagar is False else ORANGE) if es_final else colors.white
            c.setFillColor(fill)
            c.setStrokeColor(BORDER)
            c.rect(bx, top - h, box_w, h, fill=1, stroke=1)

            text_color = colors.white if es_final else TEXT_MUTED
            c.setFillColor(text_color)
            label_size = self._fit_font(label, "Helvetica-Bold", 7, box_w - 4 * mm)
            c.setFont("Helvetica-Bold", label_size)
            c.drawCentredString(bx + box_w / 2, top - 6 * mm, label)
            c.setFillColor(colors.white if es_final else NAVY_2)
            valor_txt = _clp(valor)
            valor_size = self._fit_font(valor_txt, "Helvetica-Bold", 12, box_w - 4 * mm, min_size=8)
            c.setFont("Helvetica-Bold", valor_size)
            c.drawCentredString(bx + box_w / 2, top - 14 * mm, valor_txt)

            if op:
                c.setFillColor(TEXT_MUTED)
                c.setFont("Helvetica-Bold", 11)
                c.drawCentredString(bx - gap / 2, top - h / 2 - 1.5 * mm, op)

        self.y = top - h
        self.gap(6 * mm)

    def _fit_font(self, texto, font, size, max_width, min_size=5.5):
        """Reduce el tamaño de fuente hasta que `texto` quepa en
        `max_width`, sin bajar de `min_size` (evita que etiquetas largas
        como 'COTIZACIÓN PREV. HONORARIOS' se corten en cajas angostas)."""
        c = self.c
        while size > min_size and c.stringWidth(texto, font, size) > max_width:
            size -= 0.3
        return round(size, 1)

    def _wrap(self, texto, font, size, max_width):
        c = self.c
        palabras = texto.split()
        lineas, actual = [], ""
        for palabra in palabras:
            candidata = f"{actual} {palabra}".strip()
            if c.stringWidth(candidata, font, size) <= max_width:
                actual = candidata
            else:
                if actual:
                    lineas.append(actual)
                actual = palabra
        if actual:
            lineas.append(actual)
        return lineas

    def nota_final(self):
        c = self.c
        font, size = "Helvetica-Oblique", 7.5
        texto = (
            "Este documento es un resumen referencial del cálculo del Global Complementario "
            "según la tabla del Impuesto Global Complementario del año tributario correspondiente. "
            "Los montos están expresados en pesos chilenos."
        )
        lineas = self._wrap(texto, font, size, self.width - 8 * mm)
        line_h = 3.6 * mm
        h = max(len(lineas) * line_h + 5 * mm, 12 * mm)
        self.box_frame(h, fill=BG)
        c.setFillColor(TEXT_MUTED)
        c.setFont(font, size)
        y = self.y - (h - len(lineas) * line_h) / 2 - line_h + 1 * mm
        for linea in lineas:
            c.drawString(self.x0 + 4 * mm, y, linea)
            y -= line_h
        self.y -= h


def generar_pdf_global(entrada, resultado) -> BytesIO:
    """Genera el PDF de resumen y devuelve un BytesIO listo para
    `send_file`."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    b = _PdfBuilder(c)

    b.header(entrada)
    b.datos_contribuyente(entrada)
    b.resumen_rentas(entrada, resultado)
    b.dos_columnas(resultado)
    b.resultado_impuestos(resultado)
    b.nota_final()

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
