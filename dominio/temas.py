"""Detecta de qué trata una conversación para ponerle un icono en el historial.

No usa IA (sería caro para algo tan simple): cuenta palabras clave en lo que
escribió el usuario y gana el tema con más coincidencias.
"""

import re
import unicodedata

# (icono, nombre, palabras clave sin tildes). El orden decide los empates.
TEMAS = [
    ("📦", "Envíos", {"envio", "envios", "enviar", "tarda", "entrega", "llega", "llegar", "paquete", "pedido", "seguimiento"}),
    ("💳", "Pagos", {"pago", "pagar", "tarjeta", "bizum", "paypal", "factura", "cobro"}),
    ("↩️", "Devoluciones", {"devolver", "devolucion", "garantia", "roto", "reembolso", "cambiar", "defectuoso"}),
    ("👤", "Cuenta", {"cuenta", "registro", "registrarme", "contrasena", "usuario", "login", "loguear", "logear"}),
    ("💱", "Moneda", {"euro", "euros", "dolar", "dolares", "libra", "libras", "yen", "yenes", "usd", "eur", "gbp", "jpy"}),
    ("💻", "Tecnología", {"portatil", "ordenador", "pc", "ssd", "hdd", "ram", "programar", "procesador", "movil", "pantalla", "teclado", "raton", "tablet", "gpu"}),
    ("🕘", "Horario", {"horario", "abierto", "hora", "atencion"}),
]
CALCULO = ("🧮", "Cálculos")
SALUDO = ("👋", "Saludo")
GENERAL = ("💬", "General")

_OPERACION = re.compile(r"\d\s*[+\-*/xX]\s*\d")


def _palabras(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFD", texto.casefold())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.findall(r"\w+", texto)


def _coincide(palabra: str, claves: set[str]) -> bool:
    """Igual, o empieza por una clave larga: "devolverlo" cuenta como "devolver"."""
    return palabra in claves or any(len(c) >= 5 and palabra.startswith(c) for c in claves)


def detectar_tema(preguntas: list[str]) -> tuple[str, str]:
    """Devuelve (icono, nombre) a partir de las preguntas del usuario."""
    palabras = [p for texto in preguntas for p in _palabras(texto)]
    puntos = {nombre: 0 for _, nombre, _ in TEMAS}
    for _icono, nombre, claves in TEMAS:
        puntos[nombre] = sum(1 for p in palabras if _coincide(p, claves))
    calculos = sum(1 for texto in preguntas if _OPERACION.search(texto))

    mejor_icono, mejor_nombre, mejor = GENERAL[0], GENERAL[1], 0
    for icono, nombre, _ in TEMAS:
        if puntos[nombre] > mejor:
            mejor_icono, mejor_nombre, mejor = icono, nombre, puntos[nombre]
    if calculos > mejor:
        return CALCULO
    if mejor == 0 and any(p in {"hola", "buenas", "buenos"} for p in palabras):
        return SALUDO
    return mejor_icono, mejor_nombre
