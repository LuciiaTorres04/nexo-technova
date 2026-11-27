"""Tests de ModeloHibrido.   Ejecutar:  python -m unittest test_hibrido.py -v

Comprueban la regla principal: las reglas responden lo que saben (sin gastar
nada) y SOLO lo que no saben se le pregunta a la IA.
"""

import json
import os
import unittest
from unittest import mock

from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda
from dominio.modelo_hibrido import ModeloHibrido, crear_modelo_nexo
from servicios.agente import Agente
from test_modelo import SinEsperas, crear_modelo, ok


class TestHibrido(SinEsperas):
    def setUp(self) -> None:
        super().setUp()
        # IA falsa (servidor simulado) por el SDK, igual que en test_modelo.
        self.llm, self.peticiones, _ = crear_modelo([ok("Respuesta ", "de la IA", tokens_reales=12)], sdk=True)
        self.fragmentos: list[str] = []
        self.hibrido = ModeloHibrido(llm=self.llm)
        self.hibrido.al_recibir_fragmento = self.fragmentos.append
        self.agente = Agente(self.hibrido, [Calculadora(), ConversorMoneda(), BuscadorFAQ()])

    def test_lo_que_saben_las_reglas_no_llega_a_la_ia(self) -> None:
        for pregunta, esperado in [
            ("¿Cuánto tarda el envío?", "24-48 h"),
            ("100 euros a dolares", "108.70 USD"),
            ("calcula 15 * 4", "60"),
            ("hola", "Soy NEXO"),
        ]:
            with self.subTest(pregunta=pregunta):
                respuesta = self.agente.procesar(pregunta)
                self.assertIn(esperado, respuesta)
                self.assertEqual(self.hibrido.ultima_fuente["tipo"], "reglas")
                self.assertIsNone(self.hibrido.ultimo_uso)  # 0 tokens
        self.assertEqual(len(self.peticiones), 0, "No se debe gastar ni una llamada a la IA")

    def test_lo_que_no_saben_las_reglas_lo_responde_la_ia(self) -> None:
        respuesta = self.agente.procesar("Recomiéndame un portátil para programar")
        self.assertEqual(respuesta, "Respuesta de la IA")
        self.assertEqual(self.fragmentos, ["Respuesta ", "de la IA"])  # llega en streaming
        self.assertEqual(self.hibrido.ultima_fuente["tipo"], "ia")
        self.assertIn("SDK OpenAI", self.hibrido.ultima_fuente["detalle"])
        self.assertIn("modelo-de-prueba", self.hibrido.ultima_fuente["detalle"])
        self.assertEqual(self.hibrido.ultimo_uso["output_tokens"], 12)
        self.assertEqual(len(self.peticiones), 1)

    def test_si_la_faq_no_encuentra_nada_pregunta_a_la_ia(self) -> None:
        # "registro" activa la FAQ, pero ninguna pregunta frecuente encaja
        # (la FAQ habla de "registrarme", no de "registro").
        respuesta = self.agente.procesar("¿Hay registro de visitas en la tienda?")
        self.assertEqual(respuesta, "Respuesta de la IA")
        roles = [m.rol for m in self.agente.conversacion.get_mensajes()]
        self.assertIn("herramienta", roles)  # primero lo intentó con la FAQ

    def test_la_ia_recibe_la_conversacion_completa(self) -> None:
        self.agente.procesar("hola")  # lo responden las reglas
        self.agente.procesar("¿Qué es un SSD?")  # lo responde la IA
        enviados = json.loads(self.peticiones[0].content)["messages"]
        self.assertEqual([m["role"] for m in enviados], ["system", "user", "assistant", "user"])

    def test_el_texto_de_las_reglas_tambien_sale_por_streaming(self) -> None:
        self.agente.procesar("hola")
        self.assertEqual(self.fragmentos, ["¡Hola! Soy NEXO, ¿en qué te ayudo?"])

    def test_sin_clave_responde_solo_con_reglas(self) -> None:
        with mock.patch.dict(os.environ, {"LLM_API_KEY": ""}):
            nexo = crear_modelo_nexo()
        self.assertIsNone(nexo.llm)
        nexo.al_recibir_fragmento = lambda _t: None
        agente = Agente(nexo, [])
        self.assertIn("No estoy seguro", agente.procesar("Recomiéndame un portátil"))
        self.assertEqual(nexo.ultima_fuente["tipo"], "reglas")


if __name__ == "__main__":
    unittest.main()
