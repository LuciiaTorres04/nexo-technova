"""Código de acceso para el modo móvil.

HTTPS cifra lo que viaja, pero no dice QUIÉN puede entrar. Cuando NEXO se abre
a la red (`web.py --movil`) se genera un código de 6 cifras que solo se ve en
la terminal: sin él, otro aparato de la red no puede usar NEXO.

    otro aparato ──► ¿tiene la cookie "ya he entrado"? ──sí──► NEXO
                                │ no
                                ▼
                     página /acceso (pide el código)
"""

import secrets
import threading

from flask import Flask, Response, jsonify, redirect, render_template, request, session

# Un código de 6 cifras son un millón de combinaciones: sin límite de intentos,
# un programa las probaría todas. Por eso se bloquea tras varios fallos.
MAX_FALLOS_POR_APARATO = 5
MAX_FALLOS_EN_TOTAL = 20  # por si alguien va cambiando de dirección IP
ESTE_ORDENADOR = ("127.0.0.1", "::1")


def generar_codigo() -> str:
    # secrets (y no random): números imprevisibles, pensados para seguridad.
    return f"{secrets.randbelow(1_000_000):06d}"


def proteger(app: Flask, codigo: str) -> None:
    """Pide `codigo` a todo el que no sea este mismo ordenador."""
    # Firma la cookie de sesión. Cambia en cada arranque: las cookies de la vez
    # anterior dejan de valer.
    app.secret_key = secrets.token_bytes(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,  # el JavaScript de la página no puede leerla
        SESSION_COOKIE_SECURE=True,  # solo viaja por https
        SESSION_COOKIE_SAMESITE="Lax",  # otras webs no pueden usarla para enviar datos
    )
    fallos: dict[str, int] = {}
    candado = threading.Lock()

    def pagina(error: str | None = None, estado: int = 200) -> tuple[str, int]:
        return render_template("acceso.html", error=error), estado

    @app.before_request
    def exigir_codigo() -> Response | tuple | None:
        """Se ejecuta ANTES de cualquier ruta. Devolver None = adelante."""
        if request.remote_addr in ESTE_ORDENADOR or session.get("dentro"):
            return None
        if request.endpoint in ("acceso", "static"):  # la propia puerta y su CSS
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Falta el código de acceso. Recarga la página."), 401
        return redirect("/acceso")

    @app.route("/acceso", methods=["GET", "POST"])
    def acceso():
        if request.method == "GET":
            return pagina()
        aparato = request.remote_addr or "?"
        escrito = "".join(request.form.get("codigo", "").split())
        with candado:  # dos intentos a la vez no pueden saltarse el límite
            if (
                fallos.get(aparato, 0) >= MAX_FALLOS_POR_APARATO
                or sum(fallos.values()) >= MAX_FALLOS_EN_TOTAL
            ):
                return pagina("Demasiados intentos. Reinicia NEXO en el ordenador.", 429)
            # compare_digest tarda lo mismo acierte o falle: el tiempo no da pistas.
            if not secrets.compare_digest(escrito.encode(), codigo.encode()):
                fallos[aparato] = fallos.get(aparato, 0) + 1
                return pagina("Código incorrecto.", 401)
            fallos.pop(aparato, None)
        session["dentro"] = True
        return redirect("/")
