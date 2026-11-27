"""Arranca NEXO en el navegador.

Uso:
    python web.py           solo en este ordenador (lo normal y lo más seguro)
    python web.py --movil   también desde el móvil, si está en la MISMA red,
                            con conexión cifrada (https) y código de acceso
"""

import socket
import sys
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda, MemoriaHistorial
from dominio.modelo_hibrido import crear_modelo_nexo
from persistencia.registro_coste import RegistroCosteLLM
from persistencia.registro_metricas import RegistroMetricas
from persistencia.registro_uso import RegistroUso
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from presentacion.acceso import generar_codigo
from presentacion.web import crear_app
from servicios.agente import Agente

CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_DATOS = CARPETA_PROYECTO / "datos"
PUERTO = 5000


def ip_local() -> str:
    """La dirección de este ordenador dentro de tu Wi-Fi (p. ej. 192.168.1.35).

    Truco: "conectar" un socket UDP hacia fuera no envía nada, pero hace que
    el sistema elija la tarjeta de red que usaría, y así sabemos su IP.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class ManejadorConPlazo(WSGIRequestHandler):
    # Segundos que se espera a una conexión callada antes de cerrarla.
    timeout = 30


def crear_servidor_movil(app, direccion: str, puerto: int) -> BaseWSGIServer:
    """Servidor del modo móvil: HTTPS, atendiendo a cada conexión por separado.

    Al salir del ordenador, lo que viaja por la red va cifrado. "adhoc" = se
    crea al arrancar un certificado propio (autofirmado) con la librería
    cryptography; como no lo ha firmado una entidad reconocida, el navegador
    avisa la primera vez.

    Ojo con el "saludo" de HTTPS (handshake): por defecto Werkzeug lo hace en
    el bucle principal, antes de repartir las conexiones. Si un aparato conecta
    y no dice nada (los navegadores del móvil lo hacen), NEXO se quedaba
    colgado para todos y ni Ctrl + C respondía. Con
    do_handshake_on_connect=False cada conexión saluda en su propio hilo.
    """
    servidor = make_server(
        direccion, puerto, app, threaded=True, ssl_context="adhoc",
        request_handler=ManejadorConPlazo,
    )
    servidor.socket.do_handshake_on_connect = False
    return servidor


def main() -> None:
    movil = "--movil" in sys.argv
    load_dotenv(CARPETA_PROYECTO / ".env")
    registro_coste = RegistroCosteLLM(CARPETA_DATOS / "uso_llm.csv")
    modelo = crear_modelo_nexo(registro_coste)
    if modelo.llm is None:
        print("⚠ No hay LLM_API_KEY en .env: NEXO solo responderá con sus reglas.")
    else:
        print(f"IA de apoyo: {modelo.etiqueta_llm} · {modelo.llm.id_modelo}")

    repositorio = RepositorioConversaciones(CARPETA_DATOS / "conversaciones")
    agente = Agente(
        modelo,
        # MemoriaHistorial recibe como "fuente" el método que lee las
        # conversaciones guardadas: el dominio no sabe de archivos.
        [Calculadora(), ConversorMoneda(), BuscadorFAQ(), MemoriaHistorial(repositorio.contenidos)],
        RegistroUso(CARPETA_DATOS / "uso.csv"),
    )
    # Solo al abrirse a la red hace falta código: se genera uno nuevo cada vez.
    codigo = generar_codigo() if movil else None
    app = crear_app(
        agente,
        registro_coste,
        repositorio,
        registro_metricas=RegistroMetricas(CARPETA_DATOS / "metricas.csv"),
        codigo_acceso=codigo,
    )

    # 127.0.0.1 = solo este ordenador. 0.0.0.0 = cualquier aparato de tu red.
    direccion = "0.0.0.0" if movil else "127.0.0.1"
    esquema = "https" if movil else "http"
    url = f"{esquema}://127.0.0.1:{PUERTO}"
    print(f"NEXO web en {url}  (Ctrl + C para parar)")
    if movil:
        print(f"📱 Desde el móvil (misma red), abre:  https://{ip_local()}:{PUERTO}")
        print("   🔒 Conexión cifrada. El navegador dirá que «no es privada» porque el")
        print("      certificado lo ha creado tu ordenador: Configuración avanzada → Continuar.")
        print(f"🔑 Código de acceso: {codigo}   (te lo pedirá el móvil)")
        print("   Dáselo solo a quien quieras que use tu NEXO (y gaste tu clave).")
    # Abre el navegador un segundo después, cuando el servidor ya escucha.
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    if movil:
        crear_servidor_movil(app, direccion, PUERTO).serve_forever()  # Ctrl + C para salir
    else:
        app.run(host=direccion, port=PUERTO, debug=False, threaded=True)


if __name__ == "__main__":
    main()
