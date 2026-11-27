import json
import os
import re
import sys
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
from dotenv import load_dotenv
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .excepciones import ErrorProveedorLLM, PeticionInvalida
from .herramientas import BuscadorFAQ, MemoriaHistorial
from .mensaje import Conversacion


class Respuesta:
    def __init__(
        self,
        texto: str | None = None,
        herramienta: str | None = None,
        argumentos: dict[str, object] | None = None,
    ) -> None:
        self.texto = texto
        self.herramienta = herramienta
        self.argumentos = argumentos or {}

    def es_llamada_herramienta(self) -> bool:
        return self.herramienta is not None


class Modelo:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre

    def responder(self, conversacion: Conversacion, herramientas: list) -> Respuesta:
        raise NotImplementedError("Cada modelo debe implementar responder().")


class ModeloEco(Modelo):
    def __init__(self) -> None:
        super().__init__("eco")

    def responder(self, conversacion: Conversacion, herramientas: list) -> Respuesta:
        mensajes = conversacion.get_mensajes()
        for mensaje in reversed(mensajes):
            if mensaje.rol == "usuario":
                return Respuesta(texto=f"Has dicho: {mensaje.contenido}")
        return Respuesta(texto="No hay ningún mensaje que responder.")


class ModeloReglas(Modelo):
    # Lo que contestan las reglas cuando no saben. ModeloHibrido lo usa para
    # decidir cuándo pasarle la pregunta a la IA.
    RESPUESTA_DESCONOCIDA = "No estoy seguro, ¿puedes reformularlo?"

    _OPERACION = re.compile(
        r"(-?\d+(?:[.,]\d+)?)\s*([+\-*/xX])\s*(-?\d+(?:[.,]\d+)?)"
    )
    _MONEDAS = {
        "eur": "EUR",
        "euro": "EUR",
        "euros": "EUR",
        "usd": "USD",
        "dolar": "USD",
        "dolares": "USD",
        "gbp": "GBP",
        "libra": "GBP",
        "libras": "GBP",
        "jpy": "JPY",
        "yen": "JPY",
        "yenes": "JPY",
    }
    _PATRON_MONEDA = re.compile(
        r"\b(?:"
        + "|".join(
            re.escape(alias)
            for alias in sorted(_MONEDAS, key=len, reverse=True)
        )
        + r")\b"
    )

    def __init__(self) -> None:
        super().__init__("reglas")

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = unicodedata.normalize("NFD", texto.casefold())
        return "".join(
            caracter
            for caracter in texto
            if unicodedata.category(caracter) != "Mn"
        )

    @staticmethod
    def _convertir_numero(texto: str) -> int | float:
        valor = float(texto.replace(",", "."))
        return int(valor) if valor.is_integer() and "." not in texto else valor

    def responder(self, conversacion: Conversacion, herramientas: list) -> Respuesta:
        mensajes = conversacion.get_mensajes()
        if not mensajes:
            return Respuesta(texto=self.RESPUESTA_DESCONOCIDA)

        ultimo = mensajes[-1]
        if ultimo.rol == "herramienta":
            # Un resultado de varias líneas (la memoria del historial) ya se ve
            # entero en la burbuja de la herramienta: no lo repetimos.
            if "\n" in ultimo.contenido:
                return Respuesta(texto=f"{MemoriaHistorial.RESPUESTA_CIERRE} ¿Necesitas algo más?")
            cierre = "" if ultimo.contenido.endswith((".", "!", "?")) else "."
            return Respuesta(
                texto=f"{ultimo.contenido}{cierre} ¿Necesitas algo más?"
            )
        if ultimo.rol != "usuario":
            return Respuesta(texto=self.RESPUESTA_DESCONOCIDA)

        texto = ultimo.contenido
        coincidencia = self._OPERACION.search(texto)
        if coincidencia:
            a, operacion, b = coincidencia.groups()
            return Respuesta(
                herramienta="calculadora",
                argumentos={
                    "a": self._convertir_numero(a),
                    "b": self._convertir_numero(b),
                    "operacion": "*" if operacion.lower() == "x" else operacion,
                },
            )

        normalizado = self._normalizar(texto)
        coincidencias_moneda = list(self._PATRON_MONEDA.finditer(normalizado))
        menciones_moneda = [
            (self._MONEDAS[coincidencia.group()], coincidencia.start(), coincidencia.end())
            for coincidencia in coincidencias_moneda
        ]
        monedas_mencionadas: list[str] = []
        for moneda, _, _ in menciones_moneda:
            if moneda not in monedas_mencionadas:
                monedas_mencionadas.append(moneda)

        if any(moneda != "EUR" for moneda in monedas_mencionadas):
            cantidad = re.search(r"-?\d+(?:[.,]\d+)?", texto)
            if cantidad:
                moneda_origen = monedas_mencionadas[0]
                moneda_destino = (
                    monedas_mencionadas[1]
                    if len(monedas_mencionadas) > 1
                    else ("EUR" if moneda_origen != "EUR" else None)
                )
                if moneda_destino is None:
                    return Respuesta(
                        texto="Indica la moneda de destino para realizar la conversión."
                    )

                if len(menciones_moneda) >= 2:
                    entre_monedas = normalizado[
                        menciones_moneda[0][2] : menciones_moneda[1][1]
                    ]
                    if re.search(r"\b(desde|from)\b", entre_monedas):
                        moneda_origen, moneda_destino = (
                            moneda_destino,
                            moneda_origen,
                        )

                return Respuesta(
                    herramienta="conversor_moneda",
                    argumentos={
                        "cantidad": self._convertir_numero(cantidad.group()),
                        "origen": moneda_origen,
                        "destino": moneda_destino,
                    },
                )

        # ¿Pregunta por conversaciones anteriores? ("¿qué me dijiste ayer?")
        # Va antes que las FAQ: "¿qué me dijiste del envío?" no es una FAQ.
        if MemoriaHistorial.PATRON_PREGUNTA.search(normalizado):
            return Respuesta(
                herramienta="memoria_historial",
                argumentos={"consulta": texto},
            )

        palabras = set(re.findall(r"\b\w+\b", normalizado))
        palabras_faq = {
            "envio",
            "devolucion",
            "devolver",
            "garantia",
            "horario",
            "atencion",
            "abierto",
            "pago",
            "tarjeta",
            "bizum",
            "paypal",
            "cancelar",
            "borrar",
            "cancelacion",
            "cuenta",
            "comprar",
            "registrarme",
            "registro",
            "logear",
            "loguearme",
            "crear",
        }
        if palabras.intersection(palabras_faq):
            return Respuesta(
                herramienta="buscador_faq",
                argumentos={"pregunta": texto},
            )
        if re.search(r"\b(hola|buenas|buenos dias|buenas tardes)\b", normalizado):
            return Respuesta(texto="¡Hola! Soy NEXO, ¿en qué te ayudo?")
        return Respuesta(texto=self.RESPUESTA_DESCONOCIDA)


# ===========================================================================
# MODELO LLM REAL
# ---------------------------------------------------------------------------
# Habla con cualquier API "compatible con OpenAI" (OpenAI, Groq, OpenRouter,
# Ollama en local...). Todas usan el mismo formato de petición y de streaming,
# así que cambiar de proveedor es cambiar LLM_API_URL y LLM_MODEL en el .env.
# ===========================================================================

URL_POR_DEFECTO = "https://api.openai.com/v1/chat/completions"
MODELO_POR_DEFECTO = "gpt-4o-mini"

# Fórmula de coste del material [3]: 0,008 € por cada 1000 tokens de salida.
PRECIO_EUR_POR_1000_TOKENS_SALIDA = 0.008

# Misma estimación que ya usa Conversacion.tokens_estimados(): 1 palabra ≈ 1,3 tokens.
# Solo se usa si el proveedor NO nos dice los tokens reales.
TOKENS_POR_PALABRA = 1.3

ROLES_API = {"system", "user", "assistant"}

# Nuestro dominio habla en español; la API, en inglés. Esta tabla traduce.
# "herramienta" no tiene equivalente directo (el rol "tool" de la API exige un
# id de llamada que aquí no tenemos), así que se manda como texto del asistente.
ROL_A_API = {"usuario": "user", "asistente": "assistant", "herramienta": "assistant"}

INTENTOS_MAXIMOS = 5


def validar_peticion(
    mensajes: list[dict[str, str]], max_tokens: int, temperature: float
) -> None:
    """Comprueba la petición ANTES de enviarla (material [2]).

    Si algo está mal fallamos aquí, gratis y al instante, en lugar de gastar
    una llamada de red para que el proveedor nos devuelva un 400.
    """
    if not isinstance(mensajes, list) or not mensajes:
        raise PeticionInvalida("La lista de mensajes no puede estar vacía.")

    for posicion, mensaje in enumerate(mensajes):
        if not isinstance(mensaje, dict) or "role" not in mensaje or "content" not in mensaje:
            raise PeticionInvalida(
                f"El mensaje {posicion} debe ser un dict con 'role' y 'content'."
            )
        if mensaje["role"] not in ROLES_API:
            raise PeticionInvalida(
                f"Rol no válido en el mensaje {posicion}: {mensaje['role']!r}. "
                f"Usa uno de {sorted(ROLES_API)}."
            )
        if not isinstance(mensaje["content"], str) or not mensaje["content"].strip():
            raise PeticionInvalida(f"El mensaje {posicion} no tiene contenido.")
        if mensaje["role"] == "system" and posicion != 0:
            raise PeticionInvalida("El mensaje 'system' solo puede ir el primero.")

    # Se permite un 'system' inicial (instrucciones para el modelo), pero la
    # conversación propiamente dicha tiene que empezar con el usuario.
    if mensajes[0]["role"] == "system" and len(mensajes) == 1:
        raise PeticionInvalida("Solo hay mensaje 'system': falta la pregunta del usuario.")
    primero = mensajes[1] if mensajes[0]["role"] == "system" else mensajes[0]
    if primero["role"] != "user":
        raise PeticionInvalida("El primer mensaje de la conversación debe ser de rol 'user'.")

    # isinstance(True, int) es True en Python, por eso excluimos bool a mano.
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise PeticionInvalida("max_tokens debe ser un número entero mayor que 0.")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not 0 <= temperature <= 2
    ):
        raise PeticionInvalida("temperature debe estar en el rango [0, 2].")


def calcular_coste(tokens_salida: int) -> float:
    """Coste en euros según la fórmula de [3]."""
    return tokens_salida * PRECIO_EUR_POR_1000_TOKENS_SALIDA / 1000


def estimar_tokens(texto: str) -> int:
    return round(len(texto.split()) * TOKENS_POR_PALABRA)


def es_error_reintentable(error: BaseException) -> bool:
    """Decide si merece la pena volver a intentarlo.

    - 429 (demasiadas peticiones) y 5xx (fallo del servidor) son temporales:
      esperar y repetir suele funcionar.
    - 400, 401, 403, 404... son culpa nuestra (petición mal hecha, clave mala):
      repetir daría exactamente el mismo error, así que no se reintenta.
    - Errores de red (timeout, conexión caída) también son temporales.
    """
    if isinstance(error, httpx.HTTPStatusError):
        codigo = error.response.status_code
        return codigo == 429 or codigo >= 500
    return isinstance(error, httpx.TransportError)


def _avisar_reintento(estado: RetryCallState) -> None:
    """tenacity llama a esto antes de cada espera, para que el usuario lo vea."""
    error = estado.outcome.exception() if estado.outcome else None
    # Tanto los errores de httpx como los del SDK de OpenAI guardan la
    # respuesta HTTP en .response; los errores de red no tienen.
    codigo = getattr(getattr(error, "response", None), "status_code", None)
    motivo = f"HTTP {codigo}" if codigo else type(error).__name__
    espera = estado.next_action.sleep if estado.next_action else 0
    print(
        f"\n⏳ El proveedor respondió {motivo}. Intento {estado.attempt_number}/"
        f"{INTENTOS_MAXIMOS} fallido, reintento en {espera:.0f} s...",
        file=sys.stderr,
    )


def con_reintentos(es_reintentable: Callable[[BaseException], bool]):
    """Devuelve el decorador @retry de tenacity con nuestra política.

    Es una "fábrica de decoradores": así ModeloLLM (httpx) y ModeloLLMSDK
    (SDK de OpenAI) usan exactamente la misma política, cada uno con su
    propia función para decidir qué errores son temporales.
    """
    return retry(
        retry=retry_if_exception(es_reintentable),  # ¿cuándo reintento?
        wait=wait_exponential(multiplier=1, min=1, max=10),  # 1 s, 2 s, 4 s, 8 s
        stop=stop_after_attempt(INTENTOS_MAXIMOS),  # ¿cuándo me rindo?
        before_sleep=_avisar_reintento,  # avisar al usuario
        reraise=True,  # al rendirse, lanza el error original (no un RetryError)
    )


def explicar_error_http(codigo: int, detalle: str) -> str:
    """Convierte un código HTTP en un mensaje que ayude a arreglarlo."""
    if codigo == 400:
        consejo = "Petición rechazada: revisa roles, max_tokens y el nombre del modelo."
    elif codigo == 401:
        consejo = "Clave no válida: revisa LLM_API_KEY en el archivo .env."
    elif codigo == 403:
        consejo = "Tu clave no tiene permiso para este modelo."
    elif codigo == 404:
        consejo = "No existe esa URL o ese modelo: revisa LLM_API_URL y LLM_MODEL."
    elif codigo == 429:
        consejo = f"Límite de peticiones o sin saldo, incluso tras {INTENTOS_MAXIMOS} intentos."
    else:
        consejo = f"El proveedor está fallando, incluso tras {INTENTOS_MAXIMOS} intentos."
    return f"[HTTP {codigo}] {consejo} Detalle: {detalle}"


def leer_eventos_sse(respuesta: httpx.Response) -> Iterator[dict]:
    """Lee el streaming en formato SSE (Server-Sent Events).

    El servidor manda líneas así:
        data: {"choices":[{"delta":{"content":"Hola"}}]}
        data: {"choices":[{"delta":{"content":" mundo"}}]}
        data: [DONE]
    Cada línea "data:" es un trozo (chunk) en JSON. "[DONE]" marca el final.
    """
    for linea in respuesta.iter_lines():
        if not linea.startswith("data:"):
            continue  # líneas vacías o comentarios ": keep-alive"
        datos = linea[len("data:"):].strip()
        if datos == "[DONE]":
            return
        try:
            yield json.loads(datos)
        except json.JSONDecodeError as error:
            raise ErrorProveedorLLM(
                f"El proveedor envió un trozo que no es JSON: {datos[:80]}"
            ) from error


def _imprimir_fragmento(texto: str) -> None:
    print(texto, end="", flush=True)


# Valores que usa ModeloLLM() cuando se crea "a pelo", como en el enunciado:
#     ModeloLLM().preguntar([{"role": "user", "content": "Hola"}])
CARPETA_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_ENV = CARPETA_PROYECTO / ".env"
RUTA_CSV_POR_DEFECTO = CARPETA_PROYECTO / "datos" / "uso_llm.csv"
# Marca para distinguir "no me has dicho nada" de "registro=None" (no registres).
_REGISTRO_AUTOMATICO = object()


def _registro_por_defecto() -> object:
    # Única excepción a "el dominio no depende de la persistencia": el import se
    # hace aquí dentro y solo cuando nadie ha inyectado un registro.
    from persistencia.registro_coste import RegistroCosteLLM

    return RegistroCosteLLM(RUTA_CSV_POR_DEFECTO)


class ModeloLLM(Modelo):
    """Modelo que responde usando un LLM real a través de una API HTTP."""

    # ChatConsola mira este atributo para saber que el texto ya se va
    # imprimiendo solo (en streaming) y no debe volver a imprimirlo al final.
    hace_streaming = True

    # El prompt del sistema lleva los datos REALES de TechNova (las mismas FAQ
    # que usan las reglas). Sin ellos, la IA solo tiene conocimiento general y
    # podría inventarse una política de devoluciones. Con ellos, y con la orden
    # de no inventar, responde con datos propios o reconoce que no los tiene.
    # (Es una versión mínima de RAG: dar contexto al modelo dentro del prompt.
    # Cuesta unos tokens de entrada extra en cada llamada.)
    PROMPT_SISTEMA = (
        "Eres NEXO, el asistente de atención al cliente de la tienda TechNova. "
        "Responde siempre en español, de forma breve, clara y amable, "
        "en un máximo de 120 palabras y sin tablas.\n"
        "Datos oficiales de TechNova (es TODO lo que sabes de la tienda):\n"
        + "\n".join(f"- {dato}" for dato in BuscadorFAQ.FAQ.values())
        + "\nSi te preguntan algo concreto de TechNova que no esté en esos datos "
        "(precios, stock, tiendas físicas, el estado de un pedido...), NO lo inventes: "
        "di que no lo sabes y que contacten con atención al cliente. "
        "Nunca escribas correos, teléfonos, direcciones, páginas web, chats, pasos de un "
        "trámite ni condiciones que no estén en esos datos: para contactar di solo "
        "«contacta con atención al cliente (lunes a viernes de 9:00 a 18:00)». "
        "Las preguntas generales de tecnología sí puedes responderlas con tu conocimiento."
    )
    ESFUERZOS_RAZONAMIENTO = {"low", "medium", "high"}

    def __init__(
        self,
        modelo: str | None = None,
        *,
        api_key: str | None = None,
        url: str | None = None,
        max_tokens: int = 300,  # con 150 las respuestas se cortaban a mitad de frase
        temperature: float = 0.7,
        registro: object | None = _REGISTRO_AUTOMATICO,
        al_recibir_fragmento: Callable[[str], None] | None = None,
        cliente: httpx.Client | None = None,
        esfuerzo_razonamiento: str | None = None,
    ) -> None:
        super().__init__("llm")
        # ¿Se usa la configuración del proyecto? Solo si no nos pasan la clave.
        usa_env = api_key is None
        if usa_env:
            # No pisa las variables que ya existan en el entorno.
            load_dotenv(RUTA_ENV)
        # La clave se lee del entorno (cargado desde .env). NUNCA se escribe en
        # el código: el código acaba en GitHub.
        self._api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        if not self._api_key.strip():
            raise ErrorProveedorLLM(
                "Falta LLM_API_KEY. Copia .env.example como .env y pon tu clave."
            )
        self.id_modelo = modelo or os.getenv("LLM_MODEL") or MODELO_POR_DEFECTO
        self.url = url or os.getenv("LLM_API_URL") or URL_POR_DEFECTO
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Los modelos que "razonan" (gpt-oss, o3...) piensan en secreto antes de
        # responder y ese razonamiento GASTA tokens de max_tokens. Con "low"
        # piensan poco y queda sitio para la respuesta. Es opcional: los modelos
        # que no razonan (gpt-4o...) rechazarían el parámetro con un 400.
        esfuerzo = esfuerzo_razonamiento or os.getenv("LLM_REASONING_EFFORT") or None
        if esfuerzo is not None and esfuerzo not in self.ESFUERZOS_RAZONAMIENTO:
            raise ErrorProveedorLLM(
                f"LLM_REASONING_EFFORT debe ser low, medium o high (no {esfuerzo!r})."
            )
        self.esfuerzo_razonamiento = esfuerzo
        # Igual que Agente con registro_uso: se inyecta desde fuera para que el
        # dominio no dependa de la capa de persistencia. Si no se inyecta nada
        # y se usa el .env, se registra en datos/uso_llm.csv; si se pasa la
        # clave a mano (los tests), no se escribe en ningún archivo.
        if registro is _REGISTRO_AUTOMATICO:
            registro = _registro_por_defecto() if usa_env else None
        self.registro = registro
        self.al_recibir_fragmento = al_recibir_fragmento or _imprimir_fragmento
        # Inyectar el cliente permite que los tests usen un servidor falso.
        self._cliente = cliente or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        self.ultimo_uso: dict[str, object] | None = None

    def __repr__(self) -> str:
        # Si alguien hace print(modelo) en un log, la clave no aparece.
        return f"ModeloLLM(modelo={self.id_modelo!r}, url={self.url!r}, api_key='***')"

    # ------------------------------------------------------------------ API --
    def responder(self, conversacion: Conversacion, herramientas: list) -> Respuesta:
        """Lo que llama el Agente: misma interfaz que ModeloEco y ModeloReglas."""
        return Respuesta(texto=self.preguntar(self._a_formato_api(conversacion)))

    def preguntar(
        self,
        mensajes: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Envía los mensajes, muestra la respuesta en streaming y la registra."""
        max_tokens = self.max_tokens if max_tokens is None else max_tokens
        temperature = self.temperature if temperature is None else temperature

        # 1) Validar antes de gastar nada.
        validar_peticion(mensajes, max_tokens, temperature)

        payload = {
            "model": self.id_modelo,
            "messages": mensajes,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # Pide que el último trozo incluya los tokens REALES consumidos.
            "stream_options": {"include_usage": True},
        }
        if self.esfuerzo_razonamiento:
            payload["reasoning_effort"] = self.esfuerzo_razonamiento

        # 2) y 3) Pedir la respuesta y leer los trozos a medida que llegan.
        #    _eventos() es lo ÚNICO que cambia entre httpx y el SDK: todo lo
        #    demás (validar, juntar texto, tokens, CSV) es común.
        fragmentos: list[str] = []
        tokens_reales: int | None = None
        eventos = self._eventos(payload)
        try:
            for evento in eventos:
                if "error" in evento:
                    raise ErrorProveedorLLM(f"Error a mitad de respuesta: {evento['error']}")
                for opcion in evento.get("choices") or []:
                    trozo = (opcion.get("delta") or {}).get("content")
                    if trozo:  # el primer trozo suele traer content=None
                        fragmentos.append(trozo)
                        self.al_recibir_fragmento(trozo)
                if evento.get("usage"):
                    tokens_reales = evento["usage"].get("completion_tokens")
        finally:
            eventos.close()  # cierra la conexión aunque haya habido un error

        texto = "".join(fragmentos)
        if not texto:
            raise ErrorProveedorLLM("El modelo devolvió una respuesta vacía.")

        # 4) Registrar tokens y coste.
        estimado = tokens_reales is None
        tokens = estimar_tokens(texto) if estimado else int(tokens_reales)
        coste = calcular_coste(tokens)
        self.ultimo_uso = {"output_tokens": tokens, "coste": coste, "estimado": estimado}
        if self.registro is not None:
            self.registro.registrar(
                pregunta=self._ultima_pregunta(mensajes),
                output_tokens=tokens,
                coste=coste,
            )
        return texto

    # ------------------------------------------------------------- internos --
    def _eventos(self, payload: dict) -> Iterator[dict]:
        """Generador: va entregando cada trozo de la respuesta como un dict.

        Versión httpx: hacemos la petición HTTP y leemos el SSE "a mano".
        """
        try:
            respuesta = self._abrir_stream(payload)  # con reintentos
        except httpx.HTTPStatusError as error:
            try:
                detalle = error.response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                detalle = error.response.text[:200]
            raise ErrorProveedorLLM(
                explicar_error_http(error.response.status_code, detalle)
            ) from error
        except httpx.TransportError as error:
            raise ErrorProveedorLLM(
                f"No se pudo conectar con {self.url} tras {INTENTOS_MAXIMOS} intentos: {error}"
            ) from error

        try:
            yield from leer_eventos_sse(respuesta)
        except httpx.TransportError as error:
            # Aquí NO reintentamos: parte del texto ya salió por pantalla y
            # repetir la petición lo duplicaría.
            raise ErrorProveedorLLM(f"La conexión se cortó a mitad de respuesta: {error}") from error
        finally:
            respuesta.close()  # liberamos la conexión pase lo que pase

    @con_reintentos(es_error_reintentable)
    def _abrir_stream(self, payload: dict) -> httpx.Response:
        """Abre la petición en modo streaming y comprueba el código HTTP.

        Solo se reintenta la APERTURA: es el único momento en que todavía no
        hemos mostrado nada al usuario.
        """
        peticion = self._cliente.build_request(
            "POST",
            self.url,
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        # stream=True: devuelve en cuanto llegan las cabeceras, sin esperar al
        # texto completo. (httpx.post() esperaría a tenerlo todo: no sería streaming.)
        respuesta = self._cliente.send(peticion, stream=True)
        if respuesta.is_error:
            respuesta.read()  # leemos el cuerpo para poder mostrar el detalle del error
            respuesta.close()
            respuesta.raise_for_status()  # lanza httpx.HTTPStatusError
        return respuesta

    def _a_formato_api(self, conversacion: Conversacion) -> list[dict[str, str]]:
        mensajes = [{"role": "system", "content": self.PROMPT_SISTEMA}]
        for mensaje in conversacion.get_mensajes():
            contenido = mensaje.contenido
            if mensaje.rol == "herramienta":
                contenido = f"(Resultado de una herramienta) {contenido}"
            mensajes.append({"role": ROL_A_API[mensaje.rol], "content": contenido})
        return mensajes

    @staticmethod
    def _ultima_pregunta(mensajes: list[dict[str, str]]) -> str:
        # La pregunta ACTUAL es el último mensaje del usuario, no el primero.
        for mensaje in reversed(mensajes):
            if mensaje["role"] == "user":
                return mensaje["content"]
        return ""
