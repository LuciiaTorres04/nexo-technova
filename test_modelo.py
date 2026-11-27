"""Tests de ModeloLLM.   Ejecutar:  python -m unittest test_modelo.py -v

Ningún test llama a internet ni gasta dinero: usamos httpx.MockTransport,
un "servidor falso" que responde lo que le digamos y nos deja contar las
peticiones que recibe.
"""

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from openai import OpenAI

from dominio.excepciones import ErrorAgente, ErrorProveedorLLM, PeticionInvalida
from dominio.modelo_sdk import ModeloLLMSDK
from dominio.modelos import (
    INTENTOS_MAXIMOS,
    ModeloLLM,
    calcular_coste,
    validar_peticion,
)
from persistencia.registro_coste import RegistroCosteLLM
from servicios.agente import Agente

URL_FALSA = "https://llm.test/v1/chat/completions"
PREGUNTA = [{"role": "user", "content": "¿Cuánto tarda el envío?"}]


# --------------------------------------------------------------- utilidades --
def cuerpo_sse(*trozos: str, tokens_reales: int | None = None) -> bytes:
    """Construye una respuesta en streaming igual que la de un proveedor real."""
    eventos = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": None}}]}]
    eventos += [{"choices": [{"index": 0, "delta": {"content": t}}]} for t in trozos]
    if tokens_reales is not None:
        eventos.append({"choices": [], "usage": {"completion_tokens": tokens_reales}})
    lineas = [f"data: {json.dumps(e)}\n\n" for e in eventos] + ["data: [DONE]\n\n"]
    return "".join(lineas).encode()


def ok(*trozos: str, tokens_reales: int | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        content=cuerpo_sse(*trozos, tokens_reales=tokens_reales),
        headers={"content-type": "text/event-stream"},
    )


def error_http(codigo: int) -> httpx.Response:
    return httpx.Response(codigo, json={"error": {"message": f"error simulado {codigo}"}})


def crear_modelo(respuestas: list, sdk: bool = False, **opciones) -> tuple[ModeloLLM, list, list]:
    """Devuelve (modelo, peticiones_recibidas, fragmentos_mostrados).

    `respuestas` es la lista de lo que contesta el servidor falso en cada
    intento; si se acaba, repite la última. Un elemento que sea una excepción
    se lanza (sirve para simular que se cae la red).

    Con sdk=True crea un ModeloLLMSDK. El SDK de OpenAI usa httpx por dentro,
    así que le podemos pasar el MISMO servidor falso.
    """
    peticiones: list[httpx.Request] = []
    fragmentos: list[str] = []

    def servidor_falso(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        respuesta = respuestas[min(len(peticiones), len(respuestas)) - 1]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    cliente = httpx.Client(transport=httpx.MockTransport(servidor_falso))
    if sdk:
        cliente_sdk = OpenAI(
            api_key="clave-secreta-de-prueba",
            base_url="https://llm.test/v1",
            http_client=cliente,
            max_retries=0,
        )
        modelo = ModeloLLMSDK(
            "modelo-de-prueba",
            api_key="clave-secreta-de-prueba",
            url=URL_FALSA,
            cliente_sdk=cliente_sdk,
            al_recibir_fragmento=fragmentos.append,
            **opciones,
        )
        return modelo, peticiones, fragmentos
    modelo = ModeloLLM(
        "modelo-de-prueba",
        api_key="clave-secreta-de-prueba",
        url=URL_FALSA,
        cliente=cliente,
        al_recibir_fragmento=fragmentos.append,
        **opciones,
    )
    return modelo, peticiones, fragmentos


class SinEsperas(unittest.TestCase):
    """Base: sustituye las esperas de tenacity para que los tests no tarden 15 s.

    tenacity duerme llamando a time.sleep; lo cambiamos por un mock que
    además apunta cuántos segundos habría esperado.
    """

    def setUp(self) -> None:
        parche = mock.patch("tenacity.nap.time.sleep")
        self.dormir = parche.start()
        self.addCleanup(parche.stop)
        # Los avisos "⏳ reintento..." van a stderr; los capturamos para que
        # no ensucien la salida de los tests (y así podemos comprobarlos).
        parche_avisos = mock.patch("dominio.modelos.sys.stderr", new_callable=io.StringIO)
        self.avisos = parche_avisos.start()
        self.addCleanup(parche_avisos.stop)

    def esperas(self) -> list[float]:
        return [llamada.args[0] for llamada in self.dormir.call_args_list]


# ------------------------------------------------------ (a) validación ------
class TestValidacion(unittest.TestCase):
    def test_lista_vacia_lanza_excepcion(self) -> None:
        with self.assertRaises(PeticionInvalida):
            validar_peticion([], 150, 0.7)

    def test_mensaje_vacio_no_llega_a_enviarse(self) -> None:
        modelo, peticiones, _ = crear_modelo([ok("hola")])
        with self.assertRaises(PeticionInvalida):
            modelo.preguntar([{"role": "user", "content": "   "}])
        self.assertEqual(len(peticiones), 0, "No debe gastar ninguna llamada de red")

    def test_primer_mensaje_debe_ser_user(self) -> None:
        with self.assertRaises(PeticionInvalida):
            validar_peticion([{"role": "assistant", "content": "hola"}], 150, 0.7)
        with self.assertRaises(PeticionInvalida):
            validar_peticion(
                [{"role": "system", "content": "s"}, {"role": "assistant", "content": "a"}], 150, 0.7
            )

    def test_system_inicial_permitido_pero_no_solo(self) -> None:
        validar_peticion([{"role": "system", "content": "s"}, *PREGUNTA], 150, 0.7)
        with self.assertRaises(PeticionInvalida):
            validar_peticion([{"role": "system", "content": "s"}], 150, 0.7)

    def test_rol_desconocido(self) -> None:
        with self.assertRaises(PeticionInvalida):
            validar_peticion([{"role": "usuario", "content": "hola"}], 150, 0.7)

    def test_max_tokens(self) -> None:
        for valor in (0, -5, 1.5, "150", True):
            with self.subTest(max_tokens=valor), self.assertRaises(PeticionInvalida):
                validar_peticion(PREGUNTA, valor, 0.7)

    def test_temperature(self) -> None:
        for valor in (-0.1, 2.01, "1", None):
            with self.subTest(temperature=valor), self.assertRaises(PeticionInvalida):
                validar_peticion(PREGUNTA, 150, valor)
        for valor in (0, 2, 1.3):  # los límites del rango son válidos
            validar_peticion(PREGUNTA, 150, valor)

    def test_es_un_error_controlado_del_agente(self) -> None:
        # Por eso ChatConsola lo captura y no se cae el programa.
        self.assertTrue(issubclass(PeticionInvalida, ErrorAgente))


# ------------------------------------------------------ streaming ------------
class TestStreaming(SinEsperas):
    def test_muestra_cada_fragmento_en_orden_y_devuelve_el_texto(self) -> None:
        modelo, _, fragmentos = crear_modelo([ok("Los envíos ", "tardan ", "24-48 h.")])
        texto = modelo.preguntar(PREGUNTA)
        self.assertEqual(fragmentos, ["Los envíos ", "tardan ", "24-48 h."])
        self.assertEqual(texto, "Los envíos tardan 24-48 h.")

    def test_peticion_bien_formada(self) -> None:
        modelo, peticiones, _ = crear_modelo([ok("hola")], max_tokens=50, temperature=0.2)
        modelo.preguntar(PREGUNTA)
        cuerpo = json.loads(peticiones[0].content)
        self.assertTrue(cuerpo["stream"])
        self.assertEqual(cuerpo["max_tokens"], 50)
        self.assertEqual(cuerpo["temperature"], 0.2)
        self.assertEqual(cuerpo["model"], "modelo-de-prueba")
        self.assertEqual(peticiones[0].headers["Authorization"], "Bearer clave-secreta-de-prueba")

    def test_esfuerzo_de_razonamiento_solo_si_se_configura(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_REASONING_EFFORT": ""}):
            modelo, peticiones, _ = crear_modelo([ok("hola")])
            modelo.preguntar(PREGUNTA)
            self.assertNotIn("reasoning_effort", json.loads(peticiones[0].content))

            modelo, peticiones, _ = crear_modelo([ok("hola")], esfuerzo_razonamiento="low")
            modelo.preguntar(PREGUNTA)
            self.assertEqual(json.loads(peticiones[0].content)["reasoning_effort"], "low")

            with self.assertRaises(ErrorProveedorLLM):
                crear_modelo([ok("hola")], esfuerzo_razonamiento="muchisimo")

    def test_la_clave_no_aparece_al_imprimir_el_modelo(self) -> None:
        modelo, _, _ = crear_modelo([ok("hola")])
        self.assertNotIn("clave-secreta-de-prueba", repr(modelo))
        self.assertNotIn("clave-secreta-de-prueba", str(modelo))

    def test_sin_clave_avisa_claramente(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_API_KEY": ""}):
            with self.assertRaisesRegex(ErrorProveedorLLM, "LLM_API_KEY"):
                ModeloLLM()

    def test_sin_argumentos_lee_el_env_y_registra_en_csv(self) -> None:
        # El uso del enunciado: ModeloLLM() a secas. Se prueba con un .env y un
        # CSV temporales para no tocar los de verdad.
        with tempfile.TemporaryDirectory() as carpeta:
            env = Path(carpeta) / ".env"
            env.write_text("LLM_API_KEY=clave-del-env\n", encoding="utf-8")
            csv_temporal = Path(carpeta) / "uso_llm.csv"
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch("dominio.modelos.RUTA_ENV", env), \
                    mock.patch("dominio.modelos.RUTA_CSV_POR_DEFECTO", csv_temporal):
                modelo = ModeloLLM()
                self.assertEqual(modelo._api_key, "clave-del-env")
                self.assertEqual(modelo.registro.ruta, csv_temporal)
                self.assertIsNone(ModeloLLM(registro=None).registro)  # None = no registrar

    def test_con_clave_a_mano_no_escribe_en_ningun_archivo(self) -> None:
        modelo, _, _ = crear_modelo([ok("hola")])
        self.assertIsNone(modelo.registro)

    def test_respuesta_vacia_es_un_error(self) -> None:
        modelo, _, _ = crear_modelo([ok()])
        with self.assertRaises(ErrorProveedorLLM):
            modelo.preguntar(PREGUNTA)


# ------------------------------------------------------ (b) registro CSV -----
class TestRegistroCSV(SinEsperas):
    def setUp(self) -> None:
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / "uso_llm.csv"
        self.registro = RegistroCosteLLM(self.ruta)

    def leer_filas(self) -> list[dict[str, str]]:
        with self.ruta.open(encoding="utf-8", newline="") as archivo:
            return list(csv.DictReader(archivo))

    def test_crea_el_csv_con_cabecera_y_una_fila(self) -> None:
        modelo, _, _ = crear_modelo([ok("Tarda 24 h.", tokens_reales=42)], registro=self.registro)
        modelo.preguntar(PREGUNTA)

        with self.ruta.open(encoding="utf-8") as archivo:
            self.assertEqual(archivo.readline().strip(), "timestamp,question,output_tokens,cost")
        filas = self.leer_filas()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["question"], "¿Cuánto tarda el envío?")
        self.assertEqual(filas[0]["output_tokens"], "42")  # tokens REALES de la API
        self.assertAlmostEqual(float(filas[0]["cost"]), 42 * 0.008 / 1000)

    def test_si_la_api_no_da_tokens_se_estiman(self) -> None:
        modelo, _, _ = crear_modelo([ok("uno dos tres cuatro cinco")], registro=self.registro)
        modelo.preguntar(PREGUNTA)
        self.assertEqual(self.leer_filas()[0]["output_tokens"], "6")  # 5 palabras * 1,3 ≈ 6
        self.assertTrue(modelo.ultimo_uso["estimado"])

    def test_registra_la_pregunta_actual_no_la_primera(self) -> None:
        modelo, _, _ = crear_modelo([ok("vale", tokens_reales=1)], registro=self.registro)
        conversacion = [
            {"role": "user", "content": "primera pregunta"},
            {"role": "assistant", "content": "respuesta"},
            {"role": "user", "content": "segunda pregunta"},
        ]
        modelo.preguntar(conversacion)
        self.assertEqual(self.leer_filas()[0]["question"], "segunda pregunta")

    def test_coste_total_coincide_con_la_formula(self) -> None:
        tokens = [12, 150, 7, 99, 1]
        for n in tokens:
            modelo, _, _ = crear_modelo([ok("x", tokens_reales=n)], registro=self.registro)
            modelo.preguntar(PREGUNTA)
        resumen = self.registro.resumen()
        self.assertEqual(resumen["tokens"], sum(tokens))
        self.assertAlmostEqual(resumen["coste"], calcular_coste(sum(tokens)), places=9)

    def test_si_falla_no_se_registra_nada(self) -> None:
        modelo, _, _ = crear_modelo([error_http(400)], registro=self.registro)
        with self.assertRaises(ErrorProveedorLLM):
            modelo.preguntar(PREGUNTA)
        self.assertFalse(self.ruta.exists())


# ------------------------------------------------------ (c) reintentos -------
class TestReintentos(SinEsperas):
    def test_429_siempre_hace_5_intentos_y_se_rinde(self) -> None:
        modelo, peticiones, _ = crear_modelo([error_http(429)])
        with self.assertRaisesRegex(ErrorProveedorLLM, "429"):
            modelo.preguntar(PREGUNTA)
        self.assertEqual(len(peticiones), INTENTOS_MAXIMOS)
        self.assertEqual(len(peticiones), 5)

    def test_espera_exponencial_1_2_4_8(self) -> None:
        modelo, _, _ = crear_modelo([error_http(429)])
        with self.assertRaises(ErrorProveedorLLM):
            modelo.preguntar(PREGUNTA)
        # 5 intentos -> 4 esperas entre ellos, cada una el doble que la anterior.
        self.assertEqual(self.esperas(), [1, 2, 4, 8])
        self.assertIn("Intento 4/5", self.avisos.getvalue())  # el usuario ve qué pasa

    def test_429_dos_veces_y_luego_funciona(self) -> None:
        modelo, peticiones, _ = crear_modelo([error_http(429), error_http(429), ok("¡Por fin!")])
        self.assertEqual(modelo.preguntar(PREGUNTA), "¡Por fin!")
        self.assertEqual(len(peticiones), 3)

    def test_errores_5xx_tambien_se_reintentan(self) -> None:
        for codigo in (500, 502, 503):
            with self.subTest(codigo=codigo):
                modelo, peticiones, _ = crear_modelo([error_http(codigo), ok("ok")])
                self.assertEqual(modelo.preguntar(PREGUNTA), "ok")
                self.assertEqual(len(peticiones), 2)

    def test_errores_de_red_se_reintentan(self) -> None:
        modelo, peticiones, _ = crear_modelo([httpx.ConnectError("sin red"), ok("ok")])
        self.assertEqual(modelo.preguntar(PREGUNTA), "ok")
        self.assertEqual(len(peticiones), 2)

    def test_errores_del_cliente_no_se_reintentan(self) -> None:
        for codigo in (400, 401, 403, 404):
            with self.subTest(codigo=codigo):
                modelo, peticiones, _ = crear_modelo([error_http(codigo)])
                with self.assertRaises(ErrorProveedorLLM):
                    modelo.preguntar(PREGUNTA)
                self.assertEqual(len(peticiones), 1, "Repetir daría el mismo error")

    def test_401_explica_que_revises_la_clave(self) -> None:
        modelo, _, _ = crear_modelo([error_http(401)])
        with self.assertRaisesRegex(ErrorProveedorLLM, "LLM_API_KEY"):
            modelo.preguntar(PREGUNTA)


# ------------------------------------------------------ integración ----------
class TestIntegracionConAgente(SinEsperas):
    def test_el_agente_usa_el_llm_como_cualquier_otro_modelo(self) -> None:
        modelo, peticiones, _ = crear_modelo([ok("¡Hola! ", "Soy NEXO.")])
        agente = Agente(modelo, [])
        self.assertEqual(agente.procesar("hola"), "¡Hola! Soy NEXO.")

        roles = [m.rol for m in agente.conversacion.get_mensajes()]
        self.assertEqual(roles, ["usuario", "asistente"])
        enviados = json.loads(peticiones[0].content)["messages"]
        self.assertEqual([m["role"] for m in enviados], ["system", "user"])


# ------------------------------------------------- versión con SDK de OpenAI --
class TestModeloSDK(SinEsperas):
    """Lo mismo que arriba, pero con ModeloLLMSDK: debe comportarse igual."""

    def test_streaming_y_tokens_reales(self) -> None:
        modelo, peticiones, fragmentos = crear_modelo([ok("Hola ", "desde el SDK", tokens_reales=9)], sdk=True)
        self.assertEqual(modelo.preguntar(PREGUNTA), "Hola desde el SDK")
        self.assertEqual(fragmentos, ["Hola ", "desde el SDK"])
        self.assertEqual(modelo.ultimo_uso["output_tokens"], 9)
        self.assertEqual(str(peticiones[0].url), URL_FALSA)
        self.assertTrue(json.loads(peticiones[0].content)["stream"])

    def test_429_cinco_intentos_con_tenacity(self) -> None:
        modelo, peticiones, _ = crear_modelo([error_http(429)], sdk=True)
        with self.assertRaisesRegex(ErrorProveedorLLM, "429"):
            modelo.preguntar(PREGUNTA)
        self.assertEqual(len(peticiones), 5)
        self.assertEqual(self.esperas(), [1, 2, 4, 8])

    def test_401_no_se_reintenta(self) -> None:
        modelo, peticiones, _ = crear_modelo([error_http(401)], sdk=True)
        with self.assertRaisesRegex(ErrorProveedorLLM, "LLM_API_KEY"):
            modelo.preguntar(PREGUNTA)
        self.assertEqual(len(peticiones), 1)

    def test_503_y_luego_funciona(self) -> None:
        modelo, peticiones, _ = crear_modelo([error_http(503), ok("ok")], sdk=True)
        self.assertEqual(modelo.preguntar(PREGUNTA), "ok")
        self.assertEqual(len(peticiones), 2)

    def test_registra_en_el_csv_igual_que_httpx(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            registro = RegistroCosteLLM(Path(carpeta) / "uso_llm.csv")
            modelo, _, _ = crear_modelo([ok("x", tokens_reales=30)], sdk=True, registro=registro)
            modelo.preguntar(PREGUNTA)
            self.assertAlmostEqual(registro.resumen()["coste"], calcular_coste(30))

    def test_la_clave_no_aparece(self) -> None:
        modelo, _, _ = crear_modelo([ok("x")], sdk=True)
        self.assertNotIn("clave-secreta-de-prueba", repr(modelo))


if __name__ == "__main__":
    unittest.main()
