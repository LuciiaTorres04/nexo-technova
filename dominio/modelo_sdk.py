"""ModeloLLMSDK: el mismo ModeloLLM, pero usando el SDK oficial de OpenAI.

Un SDK (Software Development Kit) es una librería que el proveedor publica
para que no tengas que hacer las peticiones HTTP a mano. Comparado con la
versión httpx de modelos.py:

    httpx (a mano)                          SDK de OpenAI
    -------------------------------------   ---------------------------------
    construyo la URL, cabeceras y JSON      client.chat.completions.create()
    leo líneas "data: {...}" y [DONE]       for chunk in stream: ...
    convierto cada línea con json.loads     chunk ya es un objeto Python
    errores: httpx.HTTPStatusError          errores: openai.RateLimitError...

Lo demás (validar, juntar texto, contar tokens, CSV) lo HEREDA de ModeloLLM:
solo se reescribe el método _eventos(). Eso es herencia + polimorfismo.
"""

from collections.abc import Iterator

from openai import APIConnectionError, APIStatusError, OpenAI

from .excepciones import ErrorProveedorLLM
from .modelos import INTENTOS_MAXIMOS, ModeloLLM, con_reintentos, explicar_error_http


def es_error_reintentable_sdk(error: BaseException) -> bool:
    """Misma política que la versión httpx, con las excepciones del SDK."""
    if isinstance(error, APIStatusError):
        return error.status_code == 429 or error.status_code >= 500
    # APIConnectionError incluye también los timeouts (APITimeoutError).
    return isinstance(error, APIConnectionError)


class ModeloLLMSDK(ModeloLLM):
    def __init__(self, modelo: str | None = None, *, cliente_sdk: OpenAI | None = None, **opciones) -> None:
        super().__init__(modelo, **opciones)  # lee clave, URL, modelo, registro...
        self.nombre = "llm-sdk"
        # El SDK quiere la URL "base" (.../v1), no la del endpoint completo.
        url_base = self.url.removesuffix("/chat/completions")
        self._sdk = cliente_sdk or OpenAI(
            api_key=self._api_key,
            base_url=url_base,
            timeout=30.0,
            # El SDK ya trae reintentos propios (2 por defecto). Los apagamos
            # para usar los NUESTROS (tenacity, 5 intentos), igual que en la
            # versión httpx, y así la comparación es justa.
            max_retries=0,
        )

    def __repr__(self) -> str:
        return f"ModeloLLMSDK(modelo={self.id_modelo!r}, url={self.url!r}, api_key='***')"

    def _eventos(self, payload: dict) -> Iterator[dict]:
        try:
            stream = self._crear_stream(payload)  # con reintentos
        except APIStatusError as error:
            raise ErrorProveedorLLM(explicar_error_http(error.status_code, error.message)) from error
        except APIConnectionError as error:
            raise ErrorProveedorLLM(
                f"No se pudo conectar con {self.url} tras {INTENTOS_MAXIMOS} intentos: {error}"
            ) from error

        try:
            for chunk in stream:
                # model_dump() convierte el objeto del SDK en un dict con la
                # MISMA forma que el JSON del SSE: así ModeloLLM.preguntar()
                # lo procesa sin saber de dónde viene.
                yield chunk.model_dump()
        except APIConnectionError as error:
            raise ErrorProveedorLLM(f"La conexión se cortó a mitad de respuesta: {error}") from error
        finally:
            stream.close()

    @con_reintentos(es_error_reintentable_sdk)
    def _crear_stream(self, payload: dict):
        # payload ya trae stream=True, así que el SDK devuelve un iterador de
        # trozos en vez de esperar a la respuesta completa.
        return self._sdk.chat.completions.create(**payload)
