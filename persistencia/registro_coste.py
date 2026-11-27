import csv
from datetime import datetime
from pathlib import Path


class RegistroCosteLLM:
    """Guarda en CSV los tokens y el coste de cada respuesta del LLM.

    Va en un archivo distinto (datos/uso_llm.csv) del de herramientas
    (datos/uso.csv) porque tienen columnas diferentes: si los mezcláramos,
    RegistroUso.resumen() detectaría una cabecera inesperada y fallaría.
    """

    CAMPOS = ("timestamp", "question", "output_tokens", "cost")

    def __init__(self, ruta: str | Path = "datos/uso_llm.csv") -> None:
        self.ruta = Path(ruta)

    def registrar(self, pregunta: str, output_tokens: int, coste: float) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        # "a" = append: abre el archivo para añadir al final, o lo crea si no existe.
        necesita_cabecera = not self.ruta.exists() or self.ruta.stat().st_size == 0
        with self.ruta.open("a", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=self.CAMPOS)
            if necesita_cabecera:
                escritor.writeheader()
            escritor.writerow(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "question": pregunta,
                    "output_tokens": output_tokens,
                    # 6 decimales: con 4, una respuesta de 20 tokens (0,00016 €)
                    # se redondearía y la suma total ya no cuadraría con la fórmula.
                    "cost": f"{coste:.6f}",
                }
            )

    def leer(self) -> list[dict[str, str]]:
        if not self.ruta.exists():
            return []
        with self.ruta.open("r", encoding="utf-8", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames != list(self.CAMPOS):
                raise ValueError(f"Formato de registro CSV no válido: {self.ruta}")
            return list(lector)

    def resumen(self) -> dict[str, float]:
        filas = self.leer()
        return {
            "respuestas": len(filas),
            "tokens": sum(int(fila["output_tokens"]) for fila in filas),
            "coste": sum(float(fila["cost"]) for fila in filas),
        }
