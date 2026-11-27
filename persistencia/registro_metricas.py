import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class RegistroMetricas:
    """Una fila por respuesta de NEXO, para el panel de métricas.

    A diferencia de uso_llm.csv (que solo apunta lo que cuesta la IA), aquí se
    apuntan TODAS las respuestas, también las de las reglas: así podemos
    comparar reglas contra IA (cuántas, qué tan rápidas, cuánto se ahorra).
    """

    CAMPOS = ("timestamp", "conversacion", "fuente", "ms", "tokens", "coste")
    FUENTES = ("reglas", "ia", "eco")

    def __init__(self, ruta: str | Path = "datos/metricas.csv") -> None:
        self.ruta = Path(ruta)

    def registrar(self, conversacion: str, fuente: str, ms: float, tokens: int = 0, coste: float = 0.0) -> None:
        if fuente not in self.FUENTES:
            raise ValueError(f"Fuente desconocida: {fuente}")
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
                    "ms": f"{ms:.1f}",
                    "tokens": tokens,
                    "coste": f"{coste:.6f}",
                }
            )

    def leer(self) -> list[dict[str, str]]:
        if not self.ruta.exists():
            return []
        with self.ruta.open("r", encoding="utf-8", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames != list(self.CAMPOS):
                raise ValueError(f"Formato de métricas no válido: {self.ruta}")
            return list(lector)

    def resumen(self) -> dict[str, object]:
        """Todo lo que necesita el panel, ya calculado."""
        filas = self.leer()
        por_fuente = {f: {"respuestas": 0, "ms_total": 0.0, "tokens": 0, "coste": 0.0} for f in self.FUENTES}
        por_dia: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "coste": 0.0, "reglas": 0, "ia": 0})

        for fila in filas:
            fuente = fila["fuente"] if fila["fuente"] in por_fuente else "eco"
            datos = por_fuente[fuente]
            datos["respuestas"] += 1
            datos["ms_total"] += float(fila["ms"])
            datos["tokens"] += int(fila["tokens"])
            datos["coste"] += float(fila["coste"])
            dia = por_dia[fila["timestamp"][:10]]
            dia["tokens"] += int(fila["tokens"])
            dia["coste"] += float(fila["coste"])
            if fuente in ("reglas", "ia"):
                dia[fuente] += 1

        for datos in por_fuente.values():
            datos["ms_medio"] = datos["ms_total"] / datos["respuestas"] if datos["respuestas"] else 0.0
            del datos["ms_total"]

        ia = por_fuente["ia"]
        coste_medio_ia = ia["coste"] / ia["respuestas"] if ia["respuestas"] else 0.0
        return {
            "total": len(filas),
            "por_fuente": por_fuente,
            "por_dia": [{"dia": d, **v} for d, v in sorted(por_dia.items())],
            # Lo que habrían costado las respuestas de las reglas si las
            # hubiera respondido la IA (al coste medio de la IA).
            "ahorro": por_fuente["reglas"]["respuestas"] * coste_medio_ia,
            "coste_medio_ia": coste_medio_ia,
            "ultimas": list(reversed(filas[-15:])),
        }
