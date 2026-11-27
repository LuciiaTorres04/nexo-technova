import csv
import json
from datetime import datetime
from pathlib import Path


class RegistroUso:
    """Añade cada ejecución de herramienta a un CSV y calcula estadísticas."""

    CAMPOS = ("fecha", "herramienta", "argumentos", "exito", "milisegundos")

    def __init__(self, ruta: str | Path = "datos/uso.csv") -> None:
        self.ruta = Path(ruta)

    def registrar(
        self,
        herramienta: str,
        argumentos: dict[str, object],
        exito: bool,
        error: str = "",
        milisegundos: float = 0.0,
    ) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        necesita_cabecera = not self.ruta.exists() or self.ruta.stat().st_size == 0
        with self.ruta.open("a", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=self.CAMPOS)
            if necesita_cabecera:
                escritor.writeheader()
            escritor.writerow(
                {
                    "fecha": datetime.now().isoformat(),
                    "herramienta": herramienta,
                    "argumentos": json.dumps(
                        argumentos, ensure_ascii=False, sort_keys=True
                    ),
                    "exito": str(bool(exito)),
                    "milisegundos": f"{milisegundos:.2f}",
                }
            )

    def resumen(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        fallos = 0
        if not self.ruta.exists():
            return {"fallos": 0}

        with self.ruta.open("r", encoding="utf-8", newline="") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames != list(self.CAMPOS):
                raise ValueError(f"Formato de registro CSV no válido: {self.ruta}")
            for fila in lector:
                nombre = fila["herramienta"]
                conteo[nombre] = conteo.get(nombre, 0) + 1
                if fila["exito"].casefold() != "true":
                    fallos += 1

        conteo["fallos"] = fallos
        return conteo
