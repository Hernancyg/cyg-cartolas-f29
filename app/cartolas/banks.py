"""Bancos disponibles para la selección visual (tarjetas) — igual a
`BANKS` en la app de Streamlit. "logo" es el nombre del archivo en
`static/logos/` (o None si el banco todavía no tiene logo — se usa la
barra de color como respaldo visual)."""

BANKS = [
    {"key": "banco_de_chile", "name": "Banco de Chile", "color": "#12233F", "logo": "banco_de_chile.png"},
    {"key": "banco_estado", "name": "Banco Estado", "color": "#D3222A", "logo": "banco_estado.png"},
    {"key": "bci", "name": "Bci", "color": "#E4002B", "logo": "bci.png"},
    {"key": "santander", "name": "Santander", "color": "#EC0000", "logo": "santander.png"},
    {"key": "itau", "name": "Itaú", "color": "#004A93", "logo": "itau.png"},
    {"key": "scotiabank", "name": "Scotiabank", "color": "#EC111A", "logo": "scotiabank.png"},
    {"key": "falabella", "name": "Falabella", "color": "#6DBE45", "logo": "falabella.png"},
    {"key": "security", "name": "Security", "color": "#4A4A4A", "logo": "security.png"},
    {"key": "banco_internacional", "name": "Banco Internacional", "color": "#F5A623", "logo": "banco_internacional.png"},
    {"key": "consorcio", "name": "Consorcio", "color": "#2E8B8B", "logo": None},
]

# Mapea el nombre de la tarjeta elegida al nombre que devuelve detect_bank()
# en bank_parsers.py, para poder avisar si no calzan.
BANK_DISPLAY_TO_DETECTED = {
    "Banco de Chile": "Banco de Chile",
    "Banco Estado": "BancoEstado",
    "Bci": "BCI",
    "Santander": "Santander",
}


def bank_by_key(key):
    if key == "otros":
        return {"key": "otros", "name": "Otro banco"}
    return next((b for b in BANKS if b["key"] == key), None)
