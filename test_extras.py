"""Tests de las funciones extra: temas, métricas, historial avanzado,
Rayos X y laboratorio.   Ejecutar:  python -m unittest test_extras.py -v
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda
from dominio.modelos import ModeloReglas
from dominio.temas import detectar_tema
from persistencia.registro_metricas import RegistroMetricas
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from presentacion.web import crear_app, parecido
from servicios.agente import Agente
from test_modelo import SinEsperas, crear_modelo, ok


class TestTemas(unittest.TestCase):
    def test_detecta_el_tema_por_palabras_clave(self) -> None:
        casos = [
            (["¿Cuánto tarda el envío?"], "Envíos"),
            (["¿Puedo pagar con Bizum?"], "Pagos"),
            (["Mi pedido llegó roto, quiero devolverlo"], "Devoluciones"),
            (["100 euros a dólares"], "Moneda"),
            (["calcula 15 * 4"], "Cálculos"),
            (["Recomiéndame un portátil para programar"], "Tecnología"),
            (["hola"], "Saludo"),
            (["¿Qué tiempo hace en Marte?"], "General"),
        ]
        for preguntas, esperado in casos:
            with self.subTest(preguntas=preguntas):
                self.assertEqual(detectar_tema(preguntas)[1], esperado)


class TestParecido(unittest.TestCase):
    def test_parecido_entre_respuestas(self) -> None:
        self.assertEqual(parecido(["hola mundo", "hola mundo", "Hola, mundo"]), 1.0)
        self.assertEqual(parecido(["uno dos", "tres cuatro"]), 0.0)
        self.assertAlmostEqual(parecido(["a b", "a c"]), 1 / 3)


class TestRegistroMetricas(unittest.TestCase):
    def setUp(self) -> None:
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.registro = RegistroMetricas(Path(carpeta.name) / "metricas.csv")

    def test_resumen_y_ahorro(self) -> None:
        self.registro.registrar("aaaaaaaa", "reglas", 0.5)
        self.registro.registrar("aaaaaaaa", "reglas", 0.3)
        self.registro.registrar("aaaaaaaa", "ia", 900, 200, 0.0016)
        self.registro.registrar("bbbbbbbb", "ia", 1100, 100, 0.0008)
        r = self.registro.resumen()
        self.assertEqual(r["total"], 4)
        self.assertEqual(r["por_fuente"]["reglas"]["respuestas"], 2)
        self.assertAlmostEqual(r["por_fuente"]["reglas"]["ms_medio"], 0.4)
        self.assertAlmostEqual(r["por_fuente"]["ia"]["ms_medio"], 1000)
        self.assertEqual(r["por_fuente"]["ia"]["tokens"], 300)
        # Ahorro = respuestas de reglas × coste medio de una respuesta de IA.
        self.assertAlmostEqual(r["ahorro"], 2 * (0.0024 / 2))
        self.assertEqual(r["por_dia"][0]["tokens"], 300)

    def test_fuente_desconocida(self) -> None:
        with self.assertRaises(ValueError):
            self.registro.registrar("aaaaaaaa", "magia", 1)

    def test_sin_archivo_no_falla(self) -> None:
        self.assertEqual(self.registro.resumen()["total"], 0)


class TestRepositorioAvanzado(unittest.TestCase):
    def setUp(self) -> None:
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.repo = RepositorioConversaciones(Path(carpeta.name))
        self.agente = Agente(ModeloReglas(), [Calculadora(), ConversorMoneda(), BuscadorFAQ()])

    def guardar(self, *preguntas: str) -> str:
        # En Windows el reloj puede dar la misma hora a dos conversaciones
        # creadas a la vez; esperamos un poco para que el orden sea fiable.
        time.sleep(0.03)
        self.agente.nueva_conversacion()
        for p in preguntas:
            self.agente.procesar(p)
        return self.repo.guardar(self.agente.conversacion)

    def test_renombrar_y_orden(self) -> None:
        vieja = self.guardar("¿Cuánto tarda el envío?")
        nueva = self.guardar("calcula 2 + 2")
        self.assertEqual([r["id"] for r in self.repo.resumenes()], [nueva, vieja])  # la más reciente, primero

        self.repo.renombrar(vieja, "  Plazos   de envío ")
        conv = next(r for r in self.repo.resumenes() if r["id"] == vieja)
        self.assertEqual(conv["titulo"], "Plazos de envío")
        self.assertEqual(conv["icono"], "📦")
        self.assertEqual(self.repo.resumenes("plazos")[0]["id"], vieja)  # se busca también por título

        self.repo.renombrar(vieja, "")  # vacío = título automático
        conv = next(r for r in self.repo.resumenes() if r["id"] == vieja)
        self.assertEqual(conv["titulo"], "¿Cuánto tarda el envío?")

    def test_contenidos_para_la_memoria(self) -> None:
        id_conv = self.guardar("¿Cuánto tarda el envío?")
        self.repo.renombrar(id_conv, "Mi envío")
        (self.repo.carpeta / "deadbeef.json").write_text("{roto", encoding="utf-8")  # no debe romper nada
        todas = self.repo.contenidos()
        self.assertEqual([c["id"] for c in todas], [id_conv])
        self.assertEqual(todas[0]["titulo"], "Mi envío")
        self.assertEqual(todas[0]["mensajes"][0]["rol"], "usuario")

    def test_borrar_quita_tambien_su_titulo(self) -> None:
        id_conv = self.guardar("hola")
        self.repo.renombrar(id_conv, "Saludo")
        self.repo.borrar(id_conv)
        self.assertIsNone(self.repo.titulo(id_conv))
        self.assertEqual(self.repo.listar(), [])

    def test_no_se_puede_renombrar_lo_que_no_existe(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.repo.renombrar("abcdef12", "x")


def tokenizador_falso(texto: str) -> dict:
    trozos = texto.split(" ")
    return {"tokens": trozos, "ids": list(range(len(trozos))), "total": len(trozos),
            "estimado": len(trozos), "caracteres": len(texto), "codificacion": "falsa"}


class TestWebExtras(SinEsperas):
    def setUp(self) -> None:
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        datos = Path(carpeta.name)
        self.agente = Agente(ModeloReglas(), [Calculadora(), ConversorMoneda(), BuscadorFAQ()])
        self.metricas = RegistroMetricas(datos / "metricas.csv")
        self.lab_peticiones: list = []
        lock = threading.Lock()

        def fabrica_lab():
            modelo, peticiones, _ = crear_modelo([ok("Eslogan ", "genial", tokens_reales=3)], sdk=True)
            with lock:
                self.lab_peticiones.append(peticiones)
            return modelo

        app = crear_app(
            self.agente,
            repositorio=RepositorioConversaciones(datos / "conversaciones"),
            registro_metricas=self.metricas,
            tokenizador=tokenizador_falso,
            fabrica_laboratorio=fabrica_lab,
        )
        self.cliente = app.test_client()

    def chatear(self, texto: str) -> None:
        self.cliente.post("/api/chat", json={"mensaje": texto}).get_data()

    def test_cada_respuesta_queda_en_las_metricas(self) -> None:
        self.chatear("calcula 2 + 2")
        filas = self.metricas.leer()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["fuente"], "reglas")
        self.assertEqual(filas[0]["conversacion"], self.agente.conversacion.id)
        datos = self.cliente.get("/api/metricas").get_json()["metricas"]
        self.assertEqual(datos["por_fuente"]["reglas"]["respuestas"], 1)

    def test_pagina_de_metricas(self) -> None:
        self.assertEqual(self.cliente.get("/metricas").status_code, 200)

    def test_ya_no_existe_ni_voz_ni_informe(self) -> None:
        # Estas funciones solo están en la versión completa (carpeta nexo).
        self.chatear("hola")
        self.assertEqual(self.cliente.get(f"/informe/{self.agente.conversacion.id}").status_code, 404)
        html = self.cliente.get("/").get_data(as_text=True)
        for resto in ("microfono", "Informe PDF", "top-p"):
            self.assertNotIn(resto, html)

    def test_renombrar_por_la_api(self) -> None:
        self.chatear("hola")
        id_conv = self.agente.conversacion.id
        r = self.cliente.patch(f"/api/conversaciones/{id_conv}", json={"titulo": "Mi saludo"})
        self.assertEqual(r.status_code, 200)
        conv = self.cliente.get("/api/conversaciones").get_json()["conversaciones"][0]
        self.assertEqual(conv["titulo"], "Mi saludo")
        self.assertNotIn("fijada", conv)  # fijar ya no existe
        self.assertEqual(self.cliente.get("/api/estado").get_json()["titulo"], "Mi saludo")
        self.assertEqual(self.cliente.patch("/api/conversaciones/abcdef12", json={"titulo": "x"}).status_code, 404)
        self.assertEqual(self.cliente.patch(f"/api/conversaciones/{id_conv}", json={"titulo": 5}).status_code, 400)

    def test_valoracion_por_la_api(self) -> None:
        self.chatear("hola")
        id_conv = self.agente.conversacion.id
        r = self.cliente.post("/api/valoracion", json={"conversacion": id_conv, "fuente": "reglas", "valor": 1})
        self.assertEqual(r.status_code, 200)
        self.cliente.post("/api/valoracion", json={"conversacion": id_conv, "fuente": "ia", "valor": -1})
        resumen = self.cliente.get("/api/metricas").get_json()["valoraciones"]
        self.assertEqual(resumen["reglas"], {"positivas": 1, "negativas": 0})
        self.assertEqual(resumen["ia"], {"positivas": 0, "negativas": 1})

    def test_valoracion_invalida(self) -> None:
        for datos in (
            {"fuente": "reglas", "valor": 5},
            {"fuente": "reglas", "valor": True},  # True == 1 en Python, pero no es un número
            {"fuente": "reglas", "valor": "1"},
            {"fuente": "eco", "valor": 1},
            {"fuente": "magia", "valor": 1},
            {"valor": 1},
        ):
            with self.subTest(datos=datos):
                self.assertEqual(self.cliente.post("/api/valoracion", json=datos).status_code, 400)

    def test_la_pagina_ya_no_tiene_exportar_ni_fijar(self) -> None:
        html = self.cliente.get("/").get_data(as_text=True)
        self.assertNotIn("Exportar", html)
        self.assertNotIn("i-estrella", html)

    def test_rayos_x(self) -> None:
        r = self.cliente.post("/api/tokens", json={"textos": ["hola mundo", "uno"]})
        resultados = r.get_json()["resultados"]
        self.assertEqual(resultados[0]["tokens"], ["hola", "mundo"])
        self.assertEqual(resultados[1]["total"], 1)
        self.assertEqual(self.cliente.post("/api/tokens", json={"textos": []}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/tokens", json={"textos": "no lista"}).status_code, 400)

    def test_laboratorio_lanza_tres_veces_con_la_temperatura(self) -> None:
        r = self.cliente.post("/api/laboratorio", json={"pregunta": "Eslogan", "temperature": 1.4})
        self.assertEqual(r.status_code, 200)
        datos = r.get_json()
        self.assertEqual(len(datos["resultados"]), 3)
        self.assertEqual(datos["resultados"][0]["texto"], "Eslogan genial")
        self.assertEqual(datos["parecido"], 1.0)
        cuerpo = json.loads(self.lab_peticiones[0][0].content)
        self.assertEqual(cuerpo["temperature"], 1.4)
        self.assertNotIn("top_p", cuerpo)  # ya no se envía

    def test_laboratorio_valida(self) -> None:
        mal = [
            {"pregunta": ""},
            {"pregunta": "x" * 501},
            {"pregunta": "hola", "veces": 9},
            {"pregunta": "hola", "temperature": "caliente"},
        ]
        for datos in mal:
            with self.subTest(datos=str(datos)[:40]):
                self.assertEqual(self.cliente.post("/api/laboratorio", json=datos).status_code, 400)
        # Fuera de rango: lo detecta validar_peticion antes de llamar a la IA.
        r = self.cliente.post("/api/laboratorio", json={"pregunta": "hola", "temperature": 5})
        self.assertEqual(r.status_code, 400)
        self.assertIn("temperature", r.get_json()["error"])


class TestTokenizadorReal(unittest.TestCase):
    """Usa tiktoken de verdad (la 1.ª vez necesita internet para descargarse)."""

    def test_bpe_parte_las_palabras_raras(self) -> None:
        from dominio.excepciones import ErrorAgente
        from dominio.tokenizador import tokenizar

        try:
            r = tokenizar("Recomiéndame un portátil para programar")
        except ErrorAgente as error:
            self.skipTest(f"Tokenizador no disponible: {error}")
        self.assertEqual("".join(r["tokens"]), "Recomiéndame un portátil para programar")
        self.assertIn(" para", r["tokens"])  # palabra frecuente = 1 token
        self.assertGreater(r["total"], len("Recomiéndame un portátil para programar".split()))


if __name__ == "__main__":
    unittest.main()
