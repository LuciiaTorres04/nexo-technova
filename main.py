from pathlib import Path

from dotenv import load_dotenv

from dominio.herramientas import (
    BuscadorFAQ,
    Calculadora,
    ConversorMoneda,
    Herramienta,
    MemoriaHistorial,
)
from dominio.modelos import ModeloReglas
from persistencia.registro_coste import RegistroCosteLLM
from persistencia.registro_uso import RegistroUso
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from presentacion.chat_consola import ChatConsola
from servicios.agente import Agente

CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_DATOS = CARPETA_PROYECTO / "datos"


def main() -> None:
    # Lee el archivo .env y mete sus variables (LLM_API_KEY...) en os.environ.
    # Se hace aquí, en el punto de entrada, y no al importar un módulo del dominio.
    load_dotenv(CARPETA_PROYECTO / ".env")

    repositorio = RepositorioConversaciones(CARPETA_DATOS / "conversaciones")
    herramientas: list[Herramienta] = [
        Calculadora(),
        ConversorMoneda(),
        BuscadorFAQ(),
        MemoriaHistorial(repositorio.contenidos),
    ]
    registro = RegistroUso(CARPETA_DATOS / "uso.csv")
    registro_coste = RegistroCosteLLM(CARPETA_DATOS / "uso_llm.csv")
    agente = Agente(ModeloReglas(), herramientas, registro)
    ChatConsola(agente, repositorio, registro, registro_coste).iniciar()


if __name__ == "__main__":
    main()
