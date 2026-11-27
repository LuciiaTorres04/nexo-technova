"""Tokenizador BPE real (Tema 2), para el modo Rayos X.

Usa `tiktoken`, la librería de OpenAI, con la codificación "o200k_base": la
de los modelos GPT-4o y la base de la que usan los gpt-oss que corremos en
Groq. Así vemos los MISMOS trozos en los que el modelo parte el texto.

BPE (Byte Pair Encoding) en una frase: empieza con letras sueltas y va
fusionando las parejas que más se repiten en los textos de entrenamiento, hasta
tener ~200 000 "trozos". Por eso las palabras frecuentes son 1 token
(" para") y las raras o con tildes se parten ("Re|com|iénd|ame").
"""

from .excepciones import ErrorAgente
from .modelos import estimar_tokens

CODIFICACION = "o200k_base"
_codificador = None  # se carga la primera vez (la 1.ª vez se descarga de internet)


def _obtener_codificador():
    global _codificador
    if _codificador is None:
        try:
            import tiktoken

            _codificador = tiktoken.get_encoding(CODIFICACION)
        except Exception as error:  # sin internet la 1.ª vez, librería no instalada...
            raise ErrorAgente(f"No se pudo cargar el tokenizador {CODIFICACION}: {error}") from error
    return _codificador


def tokenizar(texto: str) -> dict[str, object]:
    """Parte el texto en tokens y compara con nuestra estimación (palabras × 1,3)."""
    codificador = _obtener_codificador()
    ids = codificador.encode(texto)
    # decode_single_token_bytes da los bytes exactos de cada token. Una tilde
    # puede quedar partida entre dos tokens (no es UTF-8 completo): en ese
    # caso se muestra el carácter de reemplazo "�", que es lo que de verdad pasa.
    trozos = [codificador.decode_single_token_bytes(i).decode("utf-8", errors="replace") for i in ids]
    return {
        "tokens": trozos,
        "ids": ids,
        "total": len(ids),
        "estimado": estimar_tokens(texto),
        "caracteres": len(texto),
        "codificacion": CODIFICACION,
    }
