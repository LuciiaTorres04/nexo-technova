import json
import re
from pathlib import Path

from dominio.mensaje import Conversacion
from dominio.temas import detectar_tema


class RepositorioConversaciones:
    """Guarda conversaciones como archivos JSON independientes."""

    _ID_VALIDO = re.compile(r"[0-9a-fA-F]{8}\Z")
    META = "_meta.json"  # títulos personalizados (listar() lo ignora)

    def __init__(self, carpeta: str | Path = "datos/conversaciones") -> None:
        self.carpeta = Path(carpeta)

    def guardar(self, conversacion: Conversacion) -> str:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        destino = self._ruta(conversacion.id)
        with destino.open("w", encoding="utf-8") as archivo:
            json.dump(conversacion.to_dict(), archivo, ensure_ascii=False, indent=2)
            archivo.write("\n")
        return conversacion.id

    def cargar(self, id_conv: str) -> Conversacion:
        ruta = self._ruta(id_conv)
        with ruta.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
        if not isinstance(datos, dict):
            raise ValueError(f"El archivo de conversación {id_conv} no contiene un objeto JSON.")
        conversacion = Conversacion.from_dict(datos)
        if conversacion.id != id_conv:
            raise ValueError("El ID de la conversación no coincide con el nombre del archivo.")
        return conversacion

    def listar(self) -> list[str]:
        if not self.carpeta.exists():
            return []
        return sorted(
            archivo.stem
            for archivo in self.carpeta.glob("*.json")
            if self._ID_VALIDO.fullmatch(archivo.stem)
        )

    def resumenes(self, buscar: str | None = None) -> list[dict[str, object]]:
        """Datos para el historial lateral, de la más reciente a la más antigua.

        Lee el JSON "en bruto" (sin crear la Conversacion) porque solo
        necesitamos el título y la fecha. Si un archivo está roto, se salta en
        vez de romper todo el historial.

        Con `buscar`, solo devuelve las conversaciones que contienen ese texto
        en CUALQUIER mensaje, junto con el fragmento donde aparece.
        """
        buscar = (buscar or "").strip().casefold()
        meta = self._leer_meta()
        resumenes = []
        for id_conv in self.listar():
            ruta = self._ruta(id_conv)
            extra = meta.get(id_conv, {})
            try:
                with ruta.open("r", encoding="utf-8") as archivo:
                    mensajes = json.load(archivo)["mensajes"]
                preguntas = [m["contenido"] for m in mensajes if m.get("rol") == "usuario"]
                fecha = mensajes[-1]["fecha"] if mensajes else ""
                fragmento = self._buscar_fragmento(mensajes, buscar) if buscar else None
            except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
                continue
            # También se puede encontrar por el título que le hayas puesto.
            if buscar and fragmento is None and buscar in extra.get("titulo", "").casefold():
                fragmento = extra["titulo"]
            if buscar and fragmento is None:
                continue  # no contiene el texto buscado
            icono, tema = detectar_tema(preguntas)
            titulo = extra.get("titulo") or " ".join((preguntas[0] if preguntas else "").split())
            resumenes.append(
                {
                    "id": id_conv,
                    "titulo": titulo[:60] + ("…" if len(titulo) > 60 else "") or "(sin título)",
                    "titulo_personalizado": bool(extra.get("titulo")),
                    "icono": icono,
                    "tema": tema,
                    "fecha": fecha,
                    "mensajes": len(mensajes),
                    "preguntas": len(preguntas),
                    "fragmento": fragmento,
                }
            )
        resumenes.sort(key=lambda r: r["fecha"], reverse=True)  # la más reciente, primero
        return resumenes

    def contenidos(self) -> list[dict[str, object]]:
        """Todas las conversaciones con sus mensajes, para la memoria de NEXO.

        Es la "fuente" que se le inyecta a MemoriaHistorial. Un archivo roto
        se salta en vez de romper la búsqueda.
        """
        resultado = []
        for id_conv in self.listar():
            try:
                with self._ruta(id_conv).open("r", encoding="utf-8") as archivo:
                    mensajes = json.load(archivo)["mensajes"]
                if not isinstance(mensajes, list):
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                continue
            titulo = self.titulo(id_conv) or next(
                (" ".join(m["contenido"].split()) for m in mensajes
                 if isinstance(m, dict) and m.get("rol") == "usuario"),
                "(sin título)",
            )
            resultado.append({"id": id_conv, "titulo": titulo, "mensajes": mensajes})
        return resultado

    # ------------------------------------------------------------ títulos --
    # Se guardan aparte, en _meta.json, para no tocar el formato de las
    # conversaciones (Conversacion.to_dict) que ya usaba el proyecto.
    def renombrar(self, id_conv: str, titulo: str) -> None:
        self._exigir_existente(id_conv)
        titulo = " ".join(str(titulo).split())[:80]
        meta = self._leer_meta()
        datos = meta.setdefault(id_conv, {})
        if titulo:
            datos["titulo"] = titulo
        else:
            datos.pop("titulo", None)  # título vacío = volver al automático
        self._guardar_meta(meta)

    def _exigir_existente(self, id_conv: str) -> None:
        if not self._ruta(id_conv).exists():
            raise FileNotFoundError(id_conv)

    def _leer_meta(self) -> dict[str, dict]:
        try:
            with (self.carpeta / self.META).open("r", encoding="utf-8") as archivo:
                meta = json.load(archivo)
            return meta if isinstance(meta, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar_meta(self, meta: dict[str, dict]) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        meta = {k: v for k, v in meta.items() if v}  # quita entradas vacías
        with (self.carpeta / self.META).open("w", encoding="utf-8") as archivo:
            json.dump(meta, archivo, ensure_ascii=False, indent=2)

    @staticmethod
    def _buscar_fragmento(mensajes: list[dict], buscar: str) -> str | None:
        """Devuelve unas palabras alrededor de la primera coincidencia."""
        for mensaje in mensajes:
            texto = " ".join(mensaje["contenido"].split())
            posicion = texto.casefold().find(buscar)
            if posicion >= 0:
                inicio = max(0, posicion - 25)
                fin = posicion + len(buscar) + 25
                return ("…" if inicio else "") + texto[inicio:fin] + ("…" if fin < len(texto) else "")
        return None

    def borrar(self, id_conv: str) -> None:
        """Borra el archivo (y su título). FileNotFoundError si no existe."""
        self._ruta(id_conv).unlink()
        meta = self._leer_meta()
        if meta.pop(id_conv, None) is not None:
            self._guardar_meta(meta)

    def titulo(self, id_conv: str) -> str | None:
        """Título personalizado, si lo tiene."""
        return self._leer_meta().get(id_conv, {}).get("titulo")

    def _ruta(self, id_conv: str) -> Path:
        if not isinstance(id_conv, str) or not self._ID_VALIDO.fullmatch(id_conv):
            raise ValueError("El ID de conversación debe tener 8 caracteres hexadecimales.")
        return self.carpeta / f"{id_conv}.json"
