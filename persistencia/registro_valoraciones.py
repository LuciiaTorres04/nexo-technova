import csv
from datetime import datetime
from pathlib import Path


class RegistroValoraciones:
    """Un 👍 o un 👎 por respuesta, para saber si la gente queda satisfecha.

    Se guarda quién respondió (reglas o IA): así el panel puede contestar a
    "¿gustan más las respuestas de las reglas o las de la IA?", que es justo la
    comparación que pide la actividad, pero con la opinión del usuario.
    """

    CAMPOS = ("timestamp", "conversacion", "fuente", "valor")
    FUENTES = ("reglas", "ia")  # el modo eco no se valora

    def __init__(self, ruta: str | Path = "datos/valoraciones.csv") -> None:
        self.ruta = Path(ruta)

    def registrar(self, conversacion: str, fuente: str, valor: int) -> None:
        if fuente not in self.FUENTES:
            raise ValueError(f"Fuente desconocida: {fuente}")
        if valor not in (1, -1):
            raise ValueError("La valoración debe ser 1 (👍) o -1 (👎).")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        necesita_cabecera = not self.ruta.exists() or self.ruta.stat().st_size == 0
        with self.ruta.open("a", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=self.CAMPOS)
            if necesita_cabecera:
                escritor.writeheader()
            escritor.writerow(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "conversacion": conversacion,
                    "fuente": fuente,
                    "valor": valor,
                }
            )

    def leer(self) -> list[dict[str, str]]:
        if not self.ruta.exists():
            return []
        with self.ruta.open("r", encoding="utf-8", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames != list(self.CAMPOS):
                raise ValueError(f"Formato de valoraciones no válido: {self.ruta}")
            return list(lector)

    def resumen(self) -> dict[str, dict[str, int]]:
        """{"reglas": {"positivas": 3, "negativas": 1}, "ia": {...}}"""
        resultado = {f: {"positivas": 0, "negativas": 0} for f in self.FUENTES}
        for fila in self.leer():
            if fila["fuente"] in resultado:
                clave = "positivas" if fila["valor"] == "1" else "negativas"
                resultado[fila["fuente"]][clave] += 1
        return resultado
