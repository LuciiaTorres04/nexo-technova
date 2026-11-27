"""Tests de la interfaz web.   Ejecutar:  python -m unittest test_web.py -v

Flask trae un "navegador de mentira" (app.test_client()) que hace peticiones
a la app sin arrancar ningún servidor.
"""

import io
import json
import logging
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
from flask import Flask

import web
from dominio.excepciones import ErrorProveedorLLM
from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda
from dominio.modelos import Modelo, ModeloReglas, Respuesta
from persistencia.registro_coste import RegistroCosteLLM
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from dominio.modelo_hibrido import ModeloHibrido
from presentacion.web import crear_app
from servicios.agente import Agente
from test_modelo import crear_modelo, ok


class ModeloStreamingFalso(Modelo):
    """Imita a ModeloLLM sin red: manda tres trozos por el callback."""

    hace_streaming = True

    def __init__(self) -> None:
        super().__init__("falso")
        self.al_recibir_fragmento = lambda _t: None
        self.ultimo_uso = None

    def responder(self, conversacion, herramientas) -> Respuesta:
        for trozo in ("Hola", ", soy", " NEXO"):
            self.al_recibir_fragmento(trozo)
        self.ultimo_uso = {"output_tokens": 3, "coste": 0.000024, "estimado": False}
        return Respuesta(texto="Hola, soy NEXO")


def sin_clave() -> Modelo:
    raise ErrorProveedorLLM("Falta LLM_API_KEY.")


class TestWeb(unittest.TestCase):
    def setUp(self) -> None:
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        datos = Path(carpeta.name)
        self.agente = Agente(ModeloReglas(), [Calculadora(), ConversorMoneda(), BuscadorFAQ()])
        app = crear_app(
            self.agente,
            RegistroCosteLLM(datos / "uso_llm.csv"),
            RepositorioConversaciones(datos / "conversaciones"),
            fabricas={"reglas": ModeloReglas, "llm": ModeloStreamingFalso, "sdk": sin_clave},
        )
        self.cliente = app.test_client()

    def chatear(self, mensaje: str) -> list[dict]:
        r = self.cliente.post("/api/chat", json={"mensaje": mensaje})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/x-ndjson")
        return [json.loads(linea) for linea in r.get_data(as_text=True).splitlines() if linea]

    def test_la_pagina_carga_con_estilos_y_script(self) -> None:
        html = self.cliente.get("/").get_data(as_text=True)
        self.assertIn("estilo.css", html)
        self.assertIn("chat.js", html)
        with self.cliente.get("/static/estilo.css") as css:
            self.assertEqual(css.status_code, 200)

    def test_reglas_muestra_la_herramienta_usada(self) -> None:
        eventos = self.chatear("100 euros a dolares")
        tipos = [e["tipo"] for e in eventos]
        self.assertEqual(tipos, ["herramienta", "fragmento", "fin"])
        self.assertIn("108.70 USD", eventos[1]["texto"])

    def test_streaming_llega_trozo_a_trozo(self) -> None:
        self.cliente.post("/api/modelo", json={"modelo": "llm"})
        eventos = self.chatear("hola")
        trozos = [e["texto"] for e in eventos if e["tipo"] == "fragmento"]
        self.assertEqual(trozos, ["Hola", ", soy", " NEXO"])
        self.assertEqual(eventos[-1]["tipo"], "fin")
        self.assertEqual(eventos[-1]["uso"]["output_tokens"], 3)
        self.assertEqual(eventos[-1]["modelo"], "llm")  # la página sabe quién respondió

    def test_la_web_dice_quien_respondio(self) -> None:
        llm, _, _ = crear_modelo([ok("Soy la IA", tokens_reales=4)], sdk=True)
        self.agente.cambiar_modelo(ModeloHibrido(llm=llm))

        fin = self.chatear("calcula 2 + 2")[-1]
        self.assertEqual(fin["fuente"]["tipo"], "reglas")
        self.assertIsNone(fin["uso"])

        eventos = self.chatear("¿Qué es un SSD?")
        self.assertEqual([e["texto"] for e in eventos if e["tipo"] == "fragmento"], ["Soy la IA"])
        self.assertEqual(eventos[-1]["fuente"]["tipo"], "ia")
        self.assertIn("SDK OpenAI", eventos[-1]["fuente"]["detalle"])
        self.assertEqual(eventos[-1]["uso"]["output_tokens"], 4)

    def test_la_pagina_ya_no_tiene_selector_de_modelo(self) -> None:
        html = self.cliente.get("/").get_data(as_text=True)
        self.assertNotIn("LLM · httpx", html)
        self.assertIn('id="eco"', html)

    def test_mensaje_vacio_o_demasiado_largo(self) -> None:
        self.assertEqual(self.cliente.post("/api/chat", json={"mensaje": "  "}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/chat", json={"mensaje": "a" * 2001}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/chat", data="no es json").status_code, 400)

    def test_sin_clave_avisa_y_no_cambia_de_modelo(self) -> None:
        r = self.cliente.post("/api/modelo", json={"modelo": "sdk"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("LLM_API_KEY", r.get_json()["error"])
        self.assertIsInstance(self.agente.modelo, ModeloReglas)

    def test_modelo_desconocido(self) -> None:
        self.assertEqual(self.cliente.post("/api/modelo", json={"modelo": "gpt-99"}).status_code, 400)

    def test_estado_y_nueva_conversacion(self) -> None:
        self.chatear("hola")
        estado = self.cliente.get("/api/estado").get_json()
        self.assertEqual(estado["modelo"], "reglas")
        self.assertEqual([m["rol"] for m in estado["mensajes"]], ["usuario", "asistente"])
        self.cliente.post("/api/nueva")
        self.assertEqual(self.cliente.get("/api/estado").get_json()["mensajes"], [])

    def test_no_se_cambia_de_modelo_mientras_responde(self) -> None:
        puede_terminar = threading.Event()

        class ModeloLento(ModeloStreamingFalso):
            def responder(self, conversacion, herramientas):
                # Manda un primer trozo (el cliente de pruebas de Flask espera
                # al primero antes de devolver) y se queda "pensando".
                self.al_recibir_fragmento("Pensando...")
                puede_terminar.wait(timeout=5)
                return super().responder(conversacion, herramientas)

        self.agente.cambiar_modelo(ModeloLento())
        respuesta = self.cliente.post("/api/chat", json={"mensaje": "hola"})  # sigue en marcha
        self.assertEqual(self.cliente.post("/api/modelo", json={"modelo": "reglas"}).status_code, 409)
        self.assertEqual(self.cliente.post("/api/nueva").status_code, 409)
        self.assertEqual(self.cliente.post("/api/chat", json={"mensaje": "otra"}).status_code, 409)
        puede_terminar.set()
        self.assertIn('"fin"', respuesta.get_data(as_text=True))
        # Terminada la respuesta, ya se puede cambiar.
        self.assertEqual(self.cliente.post("/api/modelo", json={"modelo": "reglas"}).status_code, 200)

    # ------------------------------------------------- historial lateral --
    def historial(self, q: str = "") -> list[dict]:
        return self.cliente.get(f"/api/conversaciones?q={q}").get_json()["conversaciones"]

    def test_cada_respuesta_se_guarda_sola_en_el_historial(self) -> None:
        self.assertEqual(self.historial(), [])
        self.chatear("¿Cuánto tarda el envío?")
        self.chatear("¿Puedo pagar con Bizum?")
        historial = self.historial()
        self.assertEqual(len(historial), 1)  # misma conversación, un solo archivo
        self.assertEqual(historial[0]["titulo"], "¿Cuánto tarda el envío?")
        self.assertGreaterEqual(historial[0]["mensajes"], 4)

    def test_nueva_conversacion_no_crea_archivo_hasta_el_primer_mensaje(self) -> None:
        self.chatear("hola")
        self.cliente.post("/api/nueva")
        self.assertEqual(len(self.historial()), 1)
        self.chatear("calcula 2 + 2")
        self.assertEqual(len(self.historial()), 2)

    def test_abrir_una_conversacion_guardada(self) -> None:
        self.chatear("¿Cuánto tarda el envío?")
        primera = self.cliente.get("/api/estado").get_json()["id"]
        self.cliente.post("/api/nueva")
        self.chatear("calcula 2 + 2")

        estado = self.cliente.post(f"/api/conversaciones/{primera}/abrir").get_json()
        self.assertEqual(estado["id"], primera)
        self.assertEqual(estado["mensajes"][0]["contenido"], "¿Cuánto tarda el envío?")
        # Y se puede seguir hablando en ella.
        self.chatear("¿Puedo pagar con Bizum?")
        self.assertEqual(self.agente.conversacion.id, primera)

    def test_buscar_dentro_de_los_mensajes(self) -> None:
        self.chatear("¿Puedo pagar con Bizum?")
        self.cliente.post("/api/nueva")
        self.chatear("calcula 2 + 2")
        resultados = self.historial("paypal")  # está en la RESPUESTA, no en el título
        self.assertEqual(len(resultados), 1)
        self.assertIn("PayPal", resultados[0]["fragmento"])
        self.assertEqual(self.historial("no-existe-esto"), [])

    def test_borrar_la_conversacion_abierta_empieza_otra(self) -> None:
        self.chatear("hola")
        id_conv = self.cliente.get("/api/estado").get_json()["id"]
        r = self.cliente.delete(f"/api/conversaciones/{id_conv}")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.get_json()["actual"], id_conv)
        self.assertEqual(self.historial(), [])
        self.assertEqual(self.cliente.delete(f"/api/conversaciones/{id_conv}").status_code, 404)

    def test_ids_raros_no_se_aceptan(self) -> None:
        # Evita que alguien pida rutas como ../../secreto
        self.assertIn(self.cliente.post("/api/conversaciones/..%2F..%2Fx/abrir").status_code, (400, 404))
        self.assertEqual(self.cliente.post("/api/conversaciones/zzzzzzzz/abrir").status_code, 400)
        self.assertEqual(self.cliente.post("/api/conversaciones/abcdef12/abrir").status_code, 404)

    def test_guardar(self) -> None:
        self.chatear("hola")
        r = self.cliente.post("/api/guardar")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.get_json()["id"], r"^[0-9a-f]{8}$")


class TestArranqueWeb(unittest.TestCase):
    """Cómo arranca web.py, sin levantar ningún servidor de verdad."""

    def arrancar(self, *argumentos: str) -> tuple[mock.Mock, str, str | None, str]:
        """Devuelve (servidores falsos, URL que abre el navegador, código de
        acceso, texto mostrado en la terminal)."""
        app_falsa = mock.Mock()
        servidores = mock.Mock(normal=app_falsa.run)
        with mock.patch.dict(os.environ, {"LLM_API_KEY": ""}), \
                mock.patch.object(web, "load_dotenv"), \
                mock.patch.object(web, "crear_servidor_movil", servidores.movil), \
                mock.patch.object(web, "crear_app", return_value=app_falsa) as crear, \
                mock.patch.object(web.threading, "Timer") as temporizador, \
                mock.patch.object(web.sys, "argv", ["web.py", *argumentos]), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as terminal:
            web.main()
        return (
            servidores,
            temporizador.call_args.kwargs["args"][0],
            crear.call_args.kwargs["codigo_acceso"],
            terminal.getvalue(),
        )

    def test_normal_solo_en_este_ordenador(self) -> None:
        servidores, url, codigo, _ = self.arrancar()
        self.assertEqual(servidores.normal.call_args.kwargs["host"], "127.0.0.1")
        servidores.movil.assert_not_called()
        self.assertTrue(url.startswith("http://127.0.0.1"))
        self.assertIsNone(codigo)

    def test_movil_abre_a_la_red_pero_cifrado_y_con_codigo(self) -> None:
        servidores, url, codigo, terminal = self.arrancar("--movil")
        self.assertEqual(servidores.movil.call_args.args[1], "0.0.0.0")
        servidores.movil.return_value.serve_forever.assert_called_once()
        servidores.normal.assert_not_called()  # nunca en la red sin https
        self.assertTrue(url.startswith("https://127.0.0.1"))
        self.assertRegex(codigo, r"^\d{6}$")  # nunca en la red sin código
        self.assertIn(codigo, terminal)


class TestServidorMovil(unittest.TestCase):
    """El servidor HTTPS de verdad, solo dentro de este ordenador."""

    def setUp(self) -> None:
        registro = logging.getLogger("werkzeug")
        nivel = registro.level
        registro.setLevel(logging.CRITICAL)  # sin líneas de acceso en los tests
        self.addCleanup(registro.setLevel, nivel)
        app = Flask(__name__)
        app.add_url_rule("/", view_func=lambda: "hola")
        servidor = web.crear_servidor_movil(app, "127.0.0.1", 0)  # 0 = un puerto libre
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.puerto = servidor.server_port

    def pedir(self) -> str:
        # verify=False: el certificado es autofirmado.
        return httpx.get(f"https://127.0.0.1:{self.puerto}/", verify=False, timeout=3).text

    def test_responde_por_https(self) -> None:
        self.assertEqual(self.pedir(), "hola")

    def test_una_conexion_muda_no_bloquea_a_los_demas(self) -> None:
        # Los navegadores del móvil abren conexiones "de reserva" y no envían
        # nada. Antes, una sola dejaba NEXO colgado para todos.
        mudo = socket.create_connection(("127.0.0.1", self.puerto))
        self.addCleanup(mudo.close)  # se ejecuta ANTES que shutdown
        time.sleep(0.2)
        self.assertEqual(self.pedir(), "hola")


class TestCodigoDeAcceso(unittest.TestCase):
    CODIGO = "042917"
    MOVIL = "192.168.1.50"  # otro aparato de la red

    def setUp(self) -> None:
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.repo = RepositorioConversaciones(Path(carpeta.name) / "conversaciones")
        self.app = self.nueva_app()

    def nueva_app(self, codigo: str | None = CODIGO):
        return crear_app(Agente(ModeloReglas(), []), repositorio=self.repo, codigo_acceso=codigo)

    def cliente(self, ip: str = MOVIL, app=None):
        cliente = (app or self.app).test_client()
        cliente.environ_base.update({"REMOTE_ADDR": ip, "wsgi.url_scheme": "https"})
        return cliente

    def test_sin_codigo_otro_aparato_no_entra(self) -> None:
        movil = self.cliente()
        for ruta in ("/", "/metricas"):
            r = movil.get(ruta)
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/acceso"))
        self.assertEqual(movil.get("/api/estado").status_code, 401)
        self.assertEqual(movil.get("/api/conversaciones").status_code, 401)
        self.assertEqual(movil.post("/api/chat", json={"mensaje": "hola"}).status_code, 401)
        self.assertEqual(movil.delete("/api/conversaciones/abcdef12").status_code, 401)

    def test_la_pantalla_de_acceso_y_sus_estilos_si_se_ven(self) -> None:
        movil = self.cliente()
        self.assertIn("Código de acceso", movil.get("/acceso").get_data(as_text=True))
        with movil.get("/static/estilo.css") as css:
            self.assertEqual(css.status_code, 200)

    def test_con_el_codigo_correcto_entra(self) -> None:
        movil = self.cliente()
        r = movil.post("/acceso", data={"codigo": " 042 917 "})  # con espacios también vale
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/"))
        cookie = r.headers["Set-Cookie"]
        for proteccion in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(proteccion, cookie)
        self.assertEqual(movil.get("/api/estado").status_code, 200)

    def test_codigo_incorrecto(self) -> None:
        movil = self.cliente()
        for malo in ("000000", "", "ñandú"):
            with self.subTest(malo=malo):
                self.assertEqual(movil.post("/acceso", data={"codigo": malo}).status_code, 401)
        self.assertEqual(movil.get("/api/estado").status_code, 401)

    def test_este_ordenador_no_necesita_codigo(self) -> None:
        self.assertEqual(self.cliente("127.0.0.1").get("/api/estado").status_code, 200)

    def test_tras_cinco_fallos_se_bloquea_ese_aparato(self) -> None:
        movil = self.cliente()
        for _ in range(5):
            movil.post("/acceso", data={"codigo": "000000"})
        # Ni siquiera con el código bueno.
        self.assertEqual(movil.post("/acceso", data={"codigo": self.CODIGO}).status_code, 429)
        # Otro aparato todavía puede entrar.
        otro = self.cliente("192.168.1.51")
        self.assertEqual(otro.post("/acceso", data={"codigo": self.CODIGO}).status_code, 302)

    def test_limite_total_aunque_cambien_de_direccion(self) -> None:
        for i in range(20):
            self.cliente(f"10.0.0.{i}").post("/acceso", data={"codigo": "000000"})
        nuevo = self.cliente("10.0.0.99")
        self.assertEqual(nuevo.post("/acceso", data={"codigo": self.CODIGO}).status_code, 429)

    def test_al_reiniciar_la_cookie_antigua_no_vale(self) -> None:
        movil = self.cliente()
        movil.post("/acceso", data={"codigo": self.CODIGO})
        cookie = movil.get_cookie("session")
        reiniciada = self.cliente(app=self.nueva_app())
        reiniciada.set_cookie("session", cookie.value)
        self.assertEqual(reiniciada.get("/api/estado").status_code, 401)

    def test_sin_modo_movil_no_se_pide_nada(self) -> None:
        normal = self.cliente(app=self.nueva_app(codigo=None))
        self.assertEqual(normal.get("/api/estado").status_code, 200)
        self.assertEqual(normal.get("/acceso").status_code, 404)


if __name__ == "__main__":
    unittest.main()
