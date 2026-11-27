"""Paso 4: hace las mismas 10 preguntas a ModeloReglas y a ModeloLLM.

Guarda las respuestas en listas, las muestra en consola y las exporta a
datos/comparacion.csv para poder redactar las conclusiones (paso 5).

Uso:  python comparar_modelos.py
"""

import csv
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from dominio.excepciones import ErrorAgente
from dominio.herramientas import BuscadorFAQ, Calculadora, ConversorMoneda
from dominio.modelos import Modelo, ModeloLLM, ModeloReglas
from persistencia.registro_coste import RegistroCosteLLM
from servicios.agente import Agente

CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_DATOS = CARPETA_PROYECTO / "datos"

# Mezcla a propósito: 7 que las reglas SÍ cubren y 3 que NO.
PREGUNTAS = [
    "¿Cuánto tarda el envío?",
    "¿Puedo pagar con Bizum?",
    "100 euros a dólares",
    "calcula 15 * 4",
    "Hola",
    "Quiero devolver un producto",
    "¿Cuál es vuestro horario de atención?",
    "Recomiéndame un portátil para programar",
    "¿Qué diferencia hay entre un SSD y un HDD?",
    "Mi pedido llegó roto, ¿qué hago?",
]


def preguntar(modelo: Modelo, pregunta: str) -> tuple[str, float]:
    """Devuelve (respuesta, milisegundos).

    Se crea un Agente nuevo por pregunta: así cada una empieza sin historial y
    la comparación es justa (ningún modelo se aprovecha de preguntas anteriores).
    """
    agente = Agente(modelo, [Calculadora(), ConversorMoneda(), BuscadorFAQ()])
    inicio = perf_counter()
    try:
        respuesta = agente.procesar(pregunta)
    except ErrorAgente as error:
        respuesta = f"ERROR: {error}"
    return respuesta, (perf_counter() - inicio) * 1000


def main() -> None:
    load_dotenv(CARPETA_PROYECTO / ".env")
    registro = RegistroCosteLLM(CARPETA_DATOS / "uso_llm.csv")

    reglas = ModeloReglas()
    # al_recibir_fragmento=lambda: nada -> no imprime trozo a trozo; aquí
    # preferimos una tabla limpia al final.
    try:
        llm = ModeloLLM(registro=registro, al_recibir_fragmento=lambda _trozo: None)
    except ErrorAgente as error:
        raise SystemExit(f"No se puede comparar: {error}") from None

    respuestas_reglas: list[str] = []
    respuestas_llm: list[str] = []
    ms_reglas: list[float] = []
    ms_llm: list[float] = []
    tokens_llm: list[int] = []
    costes_llm: list[float] = []

    for numero, pregunta in enumerate(PREGUNTAS, start=1):
        print(f"[{numero}/{len(PREGUNTAS)}] {pregunta}")

        texto, ms = preguntar(reglas, pregunta)
        respuestas_reglas.append(texto)
        ms_reglas.append(ms)

        llm.ultimo_uso = None
        texto, ms = preguntar(llm, pregunta)
        respuestas_llm.append(texto)
        ms_llm.append(ms)
        uso = llm.ultimo_uso or {"output_tokens": 0, "coste": 0.0}
        tokens_llm.append(int(uso["output_tokens"]))
        costes_llm.append(float(uso["coste"]))

        print(f"   REGLAS ({ms_reglas[-1]:7.1f} ms): {respuestas_reglas[-1]}")
        print(f"   LLM    ({ms_llm[-1]:7.1f} ms, {tokens_llm[-1]} tokens): {respuestas_llm[-1]}\n")

    # ---- Guardar la comparación lista a lista -------------------------------
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_DATOS / "comparacion.csv"
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(
            ["pregunta", "respuesta_reglas", "ms_reglas", "respuesta_llm", "ms_llm", "tokens_llm", "coste_llm"]
        )
        for fila in zip(PREGUNTAS, respuestas_reglas, ms_reglas, respuestas_llm, ms_llm, tokens_llm, costes_llm):
            pregunta, r_reglas, t_reglas, r_llm, t_llm, tokens, coste = fila
            escritor.writerow([pregunta, r_reglas, f"{t_reglas:.1f}", r_llm, f"{t_llm:.1f}", tokens, f"{coste:.6f}"])

    # ---- Resumen con datos para las conclusiones -----------------------------
    sin_respuesta = sum("No estoy seguro" in r for r in respuestas_reglas)
    errores_llm = sum(r.startswith("ERROR") for r in respuestas_llm)
    print("=" * 70)
    print(f"Tiempo medio  · reglas: {sum(ms_reglas) / len(ms_reglas):8.2f} ms"
          f"   · LLM: {sum(ms_llm) / len(ms_llm):8.2f} ms")
    print(f"Sin respuesta · reglas: {sin_respuesta}/{len(PREGUNTAS)}"
          f"   · errores LLM: {errores_llm}/{len(PREGUNTAS)}")
    print(f"Tokens LLM: {sum(tokens_llm)} · coste LLM: {sum(costes_llm):.6f} €"
          f" · tokens reglas: 0 · coste reglas: 0 €")
    print(f"Comparación guardada en {ruta.relative_to(CARPETA_PROYECTO)}")


if __name__ == "__main__":
    main()
