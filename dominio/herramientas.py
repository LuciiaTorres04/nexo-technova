import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime, timedelta

from .excepciones import ArgumentosInvalidos


class Herramienta:
    """Clase base de todas las herramientas que puede usar el agente."""

    def __init__(self, nombre: str, descripcion: str) -> None:
        self.nombre = nombre
        self.descripcion = descripcion

    def ejecutar(self, **kwargs: object) -> str:
        raise NotImplementedError("Cada herramienta debe implementar ejecutar()")

    def __str__(self) -> str:
        return f"🔧 {self.nombre}: {self.descripcion}"


class Calculadora(Herramienta):
    """Realiza operaciones aritméticas básicas."""

    def __init__(self) -> None:
        super().__init__("calculadora", "Realiza operaciones aritméticas básicas.")

    def ejecutar(self, **kwargs: object) -> str:
        a = kwargs.get("a")
        b = kwargs.get("b")
        operacion = kwargs.get("operacion")

        if (
            isinstance(a, bool)
            or not isinstance(a, (int, float))
            or isinstance(b, bool)
            or not isinstance(b, (int, float))
            or not isinstance(operacion, str)
        ):
            raise ArgumentosInvalidos("Indica dos números y una operación válida.")

        operaciones = {
            "+": lambda: a + b,
            "-": lambda: a - b,
            "*": lambda: a * b,
            "/": lambda: a / b,
        }
        if operacion not in operaciones:
            raise ArgumentosInvalidos(f"Operación no válida: {operacion}")
        if operacion == "/" and b == 0:
            raise ArgumentosInvalidos("No se puede dividir entre cero.")

        resultado = operaciones[operacion]()
        resultado_texto = format(resultado, ".15g")
        return f"{a} {operacion} {b} = {resultado_texto}"


class ConversorMoneda(Herramienta):
    """Convierte entre las monedas definidas en tasas respecto al euro."""

    TASAS_A_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "JPY": 0.0062}

    def __init__(self) -> None:
        super().__init__("conversor_moneda", "Convierte EUR, USD, GBP y JPY.")

    def ejecutar(self, **kwargs: object) -> str:
        cantidad = kwargs.get("cantidad")
        origen = kwargs.get("origen")
        destino = kwargs.get("destino")

        if (
            isinstance(cantidad, bool)
            or not isinstance(cantidad, (int, float))
            or not isinstance(origen, str)
            or not isinstance(destino, str)
        ):
            raise ArgumentosInvalidos(
                "Indica una cantidad numérica, una moneda de origen y otra de destino."
            )

        origen = origen.upper()
        destino = destino.upper()
        if origen not in self.TASAS_A_EUR or destino not in self.TASAS_A_EUR:
            raise ArgumentosInvalidos(f"Moneda no disponible: {origen} o {destino}")

        euros = cantidad * self.TASAS_A_EUR[origen]
        convertido = euros / self.TASAS_A_EUR[destino]
        return f"{cantidad} {origen} = {convertido:.2f} {destino}"


class BuscadorFAQ(Herramienta):
    """Busca la pregunta frecuente con más palabras compartidas."""

    FAQ = {
        "envio plazo dias tarda": (
            "Los envíos tardan 24-48 h en península y 3-5 días en islas."
        ),
        "devolucion devolver garantia": (
            "Tienes 30 días para devolver el producto sin dar explicaciones."
        ),
        "horario atencion abierto": (
            "Atendemos de lunes a viernes de 9:00 a 18:00."
        ),
        "pago tarjeta bizum paypal": (
            "Aceptamos tarjeta, Bizum y PayPal."
        ),
        "cuenta comprar registrarme loguear crear": (
            "Puedes consultar los productos de nuestra web sin registrarte, pero para comprar necesitas crear una cuenta."
        ),
        "cancelar eliminar borrar pedido": (
            "Puedes cancelar contactando con atencion al cliente."
        ),
    }

    def __init__(self) -> None:
        super().__init__("buscador_faq", "Busca respuestas en las preguntas frecuentes.")

    @staticmethod
    def _normalizar(texto: str) -> set[str]:
        texto_sin_acentos = unicodedata.normalize("NFD", texto.casefold())
        texto_sin_acentos = "".join(
            caracter
            for caracter in texto_sin_acentos
            if unicodedata.category(caracter) != "Mn"
        )
        return set(re.findall(r"\w+", texto_sin_acentos))

    def ejecutar(self, **kwargs: object) -> str:
        pregunta = kwargs.get("pregunta")
        if not isinstance(pregunta, str):
            raise ArgumentosInvalidos("La pregunta debe ser texto.")

        palabras = self._normalizar(pregunta)
        mejor_respuesta = "No encontrado"
        max_coincidencias = 0
        for claves, respuesta in self.FAQ.items():
            coincidencias = len(palabras.intersection(self._normalizar(claves)))
            if coincidencias > max_coincidencias:
                max_coincidencias = coincidencias
                mejor_respuesta = respuesta
        return mejor_respuesta


class MemoriaHistorial(Herramienta):
    """Busca en las conversaciones antiguas: "¿qué me dijiste del envío ayer?".

    Es la idea de que el historial no sea solo una pantalla, sino una
    herramienta más del agente, al lado de la calculadora y el conversor.

    Recibe una FUENTE (una función que devuelve las conversaciones guardadas)
    en vez de leer archivos ella misma: así el dominio no depende de la capa
    de persistencia (inyección de dependencias) y los tests usan datos falsos.
    """

    MAX_RESULTADOS = 3
    # Frases (sin acentos) con las que alguien pide recordar el pasado. Las usa
    # ModeloReglas para decidir cuándo llamar a esta herramienta y la propia
    # herramienta para NO devolver como resultado las preguntas de memoria
    # anteriores (si no, la memoria se encontraría a sí misma).
    PATRON_PREGUNTA = re.compile(
        r"\b(?:recuerdas|te acuerdas|hablamos|hablaste|dijiste|te dije|me dijiste|"
        r"te pregunte|me preguntaste|te comente|me comentaste|"
        r"ultima vez|conversaciones anteriores|mis conversaciones|mi historial)\b"
    )
    RESPUESTA_CIERRE = "Eso es lo que encuentro en tu historial."
    # Cómo empiezan las respuestas de esta herramienta (también las que se
    # guardaron con versiones anteriores): tampoco se buscan.
    RESPUESTAS_PROPIAS = (RESPUESTA_CIERRE, "En tu historial encuentro", "No encuentro nada en tu historial")
    # Palabras que no sirven para buscar: o son de relleno o son la propia
    # petición de memoria ("qué me dijiste", "ayer"...).
    _RELLENO = frozenset(
        "dijiste dijimos hablamos hablado hablaste pregunte preguntaste comente comentaste "
        "contaste contestaste conteste respondiste recuerdas acuerdas acuerdo ayer anteayer "
        "semana pasada pasado ultima ultimo ultimas ultimos conversacion conversaciones "
        "anterior anteriores historial sobre acerca algo como para esto esta estos esas esos "
        "cual cuales cuando donde hace dias antes otra otro tenemos hemos dime cuentame "
        "puedes podrias muestrame mostrar sabes quiero saber decirme tema temas dicho "
        "mes hoy".split()
    )

    def __init__(
        self,
        fuente: Callable[[], list[dict]],
        hoy: Callable[[], date] = date.today,
    ) -> None:
        super().__init__("memoria_historial", "Busca en tus conversaciones anteriores.")
        self._fuente = fuente
        self._hoy = hoy

    @staticmethod
    def _palabras(texto: str) -> list[str]:
        sin_acentos = unicodedata.normalize("NFD", texto.casefold())
        sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
        return re.findall(r"\w+", sin_acentos)

    def _periodo(self, palabras: list[str]) -> tuple[date, date] | None:
        """Si preguntas "ayer" o "la semana pasada", solo se mira esa fecha."""
        hoy = self._hoy()
        texto = " ".join(palabras)
        if "anteayer" in palabras or "antes de ayer" in texto:
            dia = hoy - timedelta(days=2)
            return dia, dia
        if "ayer" in palabras:
            dia = hoy - timedelta(days=1)
            return dia, dia
        if "hoy" in palabras:
            return hoy, hoy
        if "semana" in palabras:
            return hoy - timedelta(days=7), hoy
        if "mes" in palabras:
            return hoy - timedelta(days=31), hoy
        return None

    def _etiqueta_dia(self, dia: date) -> str:
        diferencia = (self._hoy() - dia).days
        if diferencia == 0:
            return "hoy"
        if diferencia == 1:
            return "ayer"
        return dia.strftime("%d/%m")

    @staticmethod
    def _recortar(texto: str, maximo: int = 100) -> str:
        texto = " ".join(texto.split()).removesuffix(" ¿Necesitas algo más?")  # coletilla de las reglas
        return texto if len(texto) <= maximo else texto[: maximo - 3].rstrip() + "..."

    def ejecutar(self, **kwargs: object) -> str:
        consulta = kwargs.get("consulta")
        if not isinstance(consulta, str):
            raise ArgumentosInvalidos("La consulta debe ser texto.")

        palabras = self._palabras(consulta)
        periodo = self._periodo(palabras)
        # Raíces de 5 letras: "envío" encuentra "envíos" y "enviar".
        claves = [
            p[:5] for p in palabras if len(p) >= 4 and p not in self._RELLENO
        ]

        encontradas = []
        for conversacion in self._fuente():
            mejor = None  # (puntos, fecha, mensaje)
            total = 0
            for mensaje in conversacion.get("mensajes", []):
                if mensaje.get("rol") not in ("usuario", "asistente"):
                    continue
                try:
                    fecha = datetime.fromisoformat(mensaje["fecha"])
                    contenido = str(mensaje["contenido"])
                except (KeyError, TypeError, ValueError):
                    continue
                if periodo and not periodo[0] <= fecha.date() <= periodo[1]:
                    continue
                texto = " ".join(self._palabras(contenido))
                # Las propias preguntas de memoria y sus respuestas no cuentan.
                if mensaje["rol"] == "usuario" and self.PATRON_PREGUNTA.search(texto):
                    continue
                if contenido.startswith(self.RESPUESTAS_PROPIAS):
                    continue
                puntos = sum(1 for clave in claves if clave in texto)
                if claves and puntos == 0:
                    continue
                total += puntos
                if mejor is None or (puntos, fecha) > (mejor[0], mejor[1]):
                    mejor = (puntos, fecha, mensaje)
            if mejor is not None:
                encontradas.append((total, mejor[1], conversacion, mejor[2]))

        if not encontradas:
            return "No encuentro nada en tu historial sobre eso."

        # Primero las que más coinciden; a igualdad, la más reciente.
        encontradas.sort(key=lambda e: (e[0], e[1]), reverse=True)
        lineas = []
        for _, fecha, conversacion, mensaje in encontradas[: self.MAX_RESULTADOS]:
            quien = "tú" if mensaje["rol"] == "usuario" else "NEXO"
            titulo = self._recortar(str(conversacion.get("titulo", "")), 40)
            lineas.append(
                f"• {self._etiqueta_dia(fecha.date())} · «{titulo}» → "
                f"{quien}: {self._recortar(str(mensaje['contenido']))}"
            )
        cabecera = (
            "En tu historial encuentro 1 conversación:"
            if len(encontradas) == 1
            else f"En tu historial encuentro {len(encontradas)} conversaciones"
            + (f" (te enseño {self.MAX_RESULTADOS}):" if len(encontradas) > self.MAX_RESULTADOS else ":")
        )
        return cabecera + "\n" + "\n".join(lineas)