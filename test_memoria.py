"""Tests de la memoria del historial, las valoraciones 👍/👎 y el prompt con
datos de TechNova.   Ejecutar:  python -m unittest test_memoria.py -v
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from dominio.excepciones import ArgumentosInvalidos
from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda, MemoriaHistorial
from dominio.modelo_hibrido import ModeloHibrido
from dominio.modelos import ModeloLLM, ModeloReglas
from persistencia.registro_valoraciones import RegistroValoraciones
from servicios.agente import Agente

HOY = date(2026, 11, 24)


def conversacion(id_conv: str, titulo: str, *mensajes: tuple[str, str, str]) -> dict:
    return {
        "id": id_conv,
        "titulo": titulo,
        "mensajes": [{"rol": r, "contenido": c, "fecha": f} for r, c, f in mensajes],
    }


HISTORIAL = [
    conversacion(
        "aaaaaaaa", "¿Cuánto tarda el envío?",
        ("usuario", "¿Cuánto tarda el envío?", "2026-11-23T10:00:00"),
        ("asistente", "Los envíos tardan 24-48 h en península.", "2026-11-23T10:00:01"),
    ),
    conversacion(
        "bbbbbbbb", "100 euros a dólares",
        ("usuario", "100 euros a dólares", "2026-11-10T18:30:00"),
        ("asistente", "100 EUR = 108.70 USD", "2026-11-10T18:30:01"),
    ),
    conversacion(
        "cccccccc", "¿Puedo pagar con Bizum?",
        ("usuario", "¿Puedo pagar con Bizum?", "2026-11-24T09:00:00"),
    ),
]


def memoria(historial: list[dict] | None = None) -> MemoriaHistorial:
    datos = HISTORIAL if historial is None else historial
    return MemoriaHistorial(lambda: datos, hoy=lambda: HOY)


class TestMemoriaHistorial(unittest.TestCase):
    def test_busca_por_palabras_clave(self) -> None:
        r = memoria().ejecutar(consulta="¿Qué me dijiste del envío?")
        self.assertIn("1 conversación", r)
        self.assertIn("Los envíos tardan 24-48 h", r)
        self.assertNotIn("dólares", r)

    def test_la_raiz_encuentra_singular_y_plural(self) -> None:
        # "envios" (sin tilde, plural) encuentra el "envío" del historial.
        self.assertIn("Los envíos tardan", memoria().ejecutar(consulta="que me dijiste de los envios"))

    def test_filtra_por_ayer(self) -> None:
        r = memoria().ejecutar(consulta="¿De qué hablamos ayer?")
        self.assertIn("ayer", r)
        self.assertIn("«¿Cuánto tarda el envío?»", r)
        self.assertNotIn("Bizum", r)  # es de hoy
        self.assertNotIn("dólares", r)  # es de hace 2 semanas

    def test_filtra_por_hoy(self) -> None:
        r = memoria().ejecutar(consulta="¿qué te pregunté hoy?")
        self.assertIn("hoy", r)
        self.assertIn("Bizum", r)
        self.assertNotIn("envío", r)

    def test_palabras_y_dia_a_la_vez(self) -> None:
        self.assertIn("No encuentro nada", memoria().ejecutar(consulta="¿qué me dijiste de los envíos hoy?"))
        self.assertIn("Los envíos tardan", memoria().ejecutar(consulta="¿qué me dijiste de los envíos ayer?"))

    def test_fecha_antigua_se_muestra_como_dia_y_mes(self) -> None:
        r = memoria().ejecutar(consulta="¿qué me dijiste de los euros?")
        self.assertIn("10/11", r)

    def test_sin_resultados(self) -> None:
        self.assertEqual(
            memoria().ejecutar(consulta="¿qué me dijiste de las vacaciones?"),
            "No encuentro nada en tu historial sobre eso.",
        )

    def test_historial_vacio(self) -> None:
        self.assertIn("No encuentro nada", memoria([]).ejecutar(consulta="¿qué me dijiste ayer?"))

    def test_sin_palabras_clave_lista_las_mas_recientes(self) -> None:
        r = memoria().ejecutar(consulta="¿de qué hablamos?")
        self.assertIn("3 conversaciones", r)
        self.assertLess(r.index("Bizum"), r.index("envío"))  # la más reciente, primero

    def test_muestra_como_mucho_tres(self) -> None:
        muchas = [
            conversacion(f"{i:08x}", f"Envío {i}", ("usuario", f"envío número {i}", f"2026-11-{10 + i:02d}T10:00:00"))
            for i in range(6)
        ]
        r = memoria(muchas).ejecutar(consulta="¿qué te pregunté del envío?")
        self.assertIn("6 conversaciones (te enseño 3)", r)
        self.assertEqual(r.count("•"), 3)

    def test_ignora_mensajes_rotos_y_de_herramientas(self) -> None:
        roto = [
            conversacion(
                "dddddddd", "Raro",
                ("herramienta", "envío secreto", "2026-11-23T10:00:00"),  # solo cuentan usuario y asistente
                ("usuario", "envío con fecha rara", "no es una fecha"),
                ("usuario", "envío bueno", "2026-11-23T10:00:00"),
            ),
            {"id": "eeeeeeee", "titulo": "Sin mensajes"},
        ]
        r = memoria(roto).ejecutar(consulta="¿qué me dijiste del envío?")
        self.assertIn("envío bueno", r)
        self.assertNotIn("secreto", r)
        self.assertNotIn("fecha rara", r)

    def test_no_se_encuentra_a_si_misma(self) -> None:
        # Las preguntas de memoria anteriores (y su respuesta) se guardan en el
        # historial, pero no deben salir como resultado de otra búsqueda.
        con_memoria = HISTORIAL + [
            conversacion(
                "ffffffff", "¿Qué me dijiste del envío?",
                ("usuario", "¿Qué me dijiste del envío?", "2026-11-24T08:00:00"),
                ("asistente", "Eso es lo que encuentro en tu historial. ¿Necesitas algo más?", "2026-11-24T08:00:01"),
            )
        ]
        r = memoria(con_memoria).ejecutar(consulta="¿qué me dijiste del envío?")
        self.assertIn("1 conversación", r)
        self.assertNotIn("ffffffff", r)
        self.assertNotIn("Eso es lo que encuentro", r)

    def test_la_consulta_debe_ser_texto(self) -> None:
        with self.assertRaises(ArgumentosInvalidos):
            memoria().ejecutar(consulta=5)
        with self.assertRaises(ArgumentosInvalidos):
            memoria().ejecutar()


class TestReglasYMemoria(unittest.TestCase):
    def pedir(self, texto: str):
        agente = Agente(ModeloReglas(), [Calculadora(), ConversorMoneda(), BuscadorFAQ(), memoria()])
        return agente.procesar(texto)

    def test_las_reglas_detectan_preguntas_sobre_el_pasado(self) -> None:
        for frase in (
            "¿Qué me dijiste del envío ayer?",
            "¿De qué hablamos la semana pasada?",
            "¿Te acuerdas de lo que te pregunté?",
            "¿Recuerdas lo del pago?",
            "¿Cuál fue la última vez que hablamos?",
        ):
            with self.subTest(frase=frase):
                r = ModeloReglas().responder(_conv(frase), [])
                self.assertEqual(r.herramienta, "memoria_historial")
                self.assertEqual(r.argumentos, {"consulta": frase})

    def test_las_preguntas_normales_no_activan_la_memoria(self) -> None:
        for frase in ("¿Cuánto tarda el envío?", "100 euros a dólares", "hola", "Recomiéndame un portátil", "calcula 2 + 2"):
            with self.subTest(frase=frase):
                r = ModeloReglas().responder(_conv(frase), [])
                self.assertNotEqual(r.herramienta, "memoria_historial")

    def test_el_agente_usa_la_memoria_de_extremo_a_extremo(self) -> None:
        agente = Agente(ModeloReglas(), [Calculadora(), ConversorMoneda(), BuscadorFAQ(), memoria()])
        respuesta = agente.procesar("¿Qué me dijiste del envío ayer?")
        resultado = next(m.contenido for m in agente.conversacion.get_mensajes() if m.rol == "herramienta")
        self.assertIn("En tu historial encuentro", resultado)
        self.assertIn("Los envíos tardan 24-48 h", resultado)
        self.assertNotIn("Necesitas", resultado)  # la coletilla de las reglas se quita
        self.assertEqual(respuesta, "Eso es lo que encuentro en tu historial. ¿Necesitas algo más?")

    def test_la_memoria_la_resuelven_las_reglas_sin_llamar_a_la_ia(self) -> None:
        class IAProhibida:
            id_modelo = "x"

            def responder(self, *_):
                raise AssertionError("La memoria no debe gastar tokens de IA")

        modelo = ModeloHibrido(llm=IAProhibida())  # type: ignore[arg-type]
        agente = Agente(modelo, [Calculadora(), ConversorMoneda(), BuscadorFAQ(), memoria()])
        agente.procesar("¿Qué me dijiste de los pagos?")
        self.assertEqual(modelo.ultima_fuente["tipo"], "reglas")

    def test_si_no_hay_nada_tampoco_se_pasa_a_la_ia(self) -> None:
        # "No encuentro nada..." no empieza por "No estoy seguro" ni "No encontrado".
        respuesta = self.pedir("¿Qué me dijiste de las vacaciones?")
        self.assertTrue(respuesta.startswith("No encuentro nada"))
        self.assertFalse(ModeloHibrido._reglas_no_saben(respuesta))


def _conv(texto: str):
    from dominio.mensaje import Conversacion, Mensaje

    c = Conversacion()
    c.agregar(Mensaje("usuario", texto))
    return c


class TestRegistroValoraciones(unittest.TestCase):
    def setUp(self) -> None:
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.registro = RegistroValoraciones(Path(carpeta.name) / "valoraciones.csv")

    def test_resumen_por_fuente(self) -> None:
        self.registro.registrar("aaaaaaaa", "reglas", 1)
        self.registro.registrar("aaaaaaaa", "reglas", 1)
        self.registro.registrar("aaaaaaaa", "ia", -1)
        self.registro.registrar("bbbbbbbb", "ia", 1)
        self.assertEqual(
            self.registro.resumen(),
            {"reglas": {"positivas": 2, "negativas": 0}, "ia": {"positivas": 1, "negativas": 1}},
        )

    def test_sin_archivo_no_falla(self) -> None:
        self.assertEqual(self.registro.resumen()["ia"], {"positivas": 0, "negativas": 0})

    def test_rechaza_valores_raros(self) -> None:
        with self.assertRaises(ValueError):
            self.registro.registrar("aaaaaaaa", "eco", 1)
        with self.assertRaises(ValueError):
            self.registro.registrar("aaaaaaaa", "ia", 0)
        self.assertFalse(self.registro.ruta.exists())  # no se creó nada

    def test_cabecera_incorrecta(self) -> None:
        self.registro.ruta.write_text("otra,cosa\n1,2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.registro.resumen()


class TestPromptConDatosDeTechNova(unittest.TestCase):
    def test_la_ia_recibe_las_faq_y_la_orden_de_no_inventar(self) -> None:
        prompt = ModeloLLM.PROMPT_SISTEMA
        for dato in BuscadorFAQ.FAQ.values():
            self.assertIn(dato, prompt)
        self.assertIn("NO lo inventes", prompt)
        self.assertIn("atención al cliente", prompt)


if __name__ == "__main__":
    unittest.main()
