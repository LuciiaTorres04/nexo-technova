"""Interfaz web de NEXO (Flask).

Es otra capa de PRESENTACIÓN, igual que chat_consola.py: usa el mismo Agente
y los mismos modelos. Solo cambia cómo se muestran las cosas.

Cómo llega el streaming hasta el navegador:

    navegador ──POST /api/chat──► Flask ──► hilo "trabajar()" ──► Agente ──► modelo
        ▲                          │                                           │
        │      línea JSON a línea  │◄────────── cola (queue.Queue) ◄───────────┘
        └──────────────────────────┘          (cada trozo que llega)

El modelo EMPUJA trozos con un callback y Flask necesita un generador que los
SAQUE: la cola une las dos cosas (patrón productor / consumidor).
"""

import json
import queue
import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from time import perf_counter

from flask import Flask, Response, jsonify, render_template, request

from dominio.excepciones import ErrorAgente
from dominio.mensaje import Conversacion
from dominio.modelo_hibrido import ModeloHibrido, crear_modelo_nexo
from dominio.modelo_sdk import ModeloLLMSDK
from dominio.modelos import Modelo, ModeloEco, ModeloLLM
from dominio.tokenizador import tokenizar
from persistencia.registro_coste import RegistroCosteLLM
from persistencia.registro_metricas import RegistroMetricas
from persistencia.registro_valoraciones import RegistroValoraciones
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from presentacion.acceso import proteger
from servicios.agente import Agente

MAX_CARACTERES = 2000
OCUPADO = "Espera a que termine la respuesta anterior."


def nombre_corto(modelo: Modelo) -> str:
    if isinstance(modelo, ModeloEco):
        return "eco"
    if isinstance(modelo, ModeloHibrido):
        return "nexo"
    if isinstance(modelo, ModeloLLMSDK):  # antes que ModeloLLM: es su hija
        return "sdk"
    if isinstance(modelo, ModeloLLM):
        return "llm"
    return "reglas"


def fuente_de(modelo: Modelo) -> str:
    """Quién respondió la última vez: "reglas", "ia" o "eco" (para las métricas)."""
    fuente = getattr(modelo, "ultima_fuente", None)
    if fuente:
        return fuente["tipo"]
    if isinstance(modelo, ModeloEco):
        return "eco"
    return "ia" if isinstance(modelo, ModeloLLM) else "reglas"


def parecido(textos: list[str]) -> float:
    """Cuánto se parecen varias respuestas (0 a 1), para el laboratorio.

    Índice de Jaccard: palabras en común / palabras en total, en cada pareja,
    y la media de todas las parejas. 1 = idénticas, 0 = nada en común.
    """
    conjuntos = [set(re.findall(r"\w+", t.casefold())) for t in textos if t]
    parejas = list(combinations(conjuntos, 2))
    if not parejas:
        return 1.0
    return sum(len(a & b) / len(a | b) if a | b else 1.0 for a, b in parejas) / len(parejas)


def crear_app(
    agente: Agente,
    registro_coste: RegistroCosteLLM | None = None,
    repositorio: RepositorioConversaciones | None = None,
    fabricas: dict[str, Callable[[], Modelo]] | None = None,
    registro_metricas: RegistroMetricas | None = None,
    tokenizador: Callable[[str], dict] = tokenizar,
    fabrica_laboratorio: Callable[[], ModeloLLM] | None = None,
    registro_valoraciones: RegistroValoraciones | None = None,
    codigo_acceso: str | None = None,
) -> Flask:
    """Crea la aplicación. Recibe sus dependencias para poder testearla.

    Con `codigo_acceso` (modo móvil), los demás aparatos tienen que escribirlo.
    """
    app = Flask(__name__)
    if codigo_acceso:
        proteger(app, codigo_acceso)
    repositorio = repositorio or RepositorioConversaciones()
    metricas = registro_metricas or RegistroMetricas(repositorio.carpeta.parent / "metricas.csv")
    valoraciones = registro_valoraciones or RegistroValoraciones(
        repositorio.carpeta.parent / "valoraciones.csv"
    )
    # El usuario no elige modelo: NEXO decide solo (reglas o IA). Solo existe
    # además el modo "eco", escondido en un botón discreto.
    fabricas = fabricas or {
        "nexo": lambda: crear_modelo_nexo(registro_coste),
        "eco": ModeloEco,
    }
    fabrica_laboratorio = fabrica_laboratorio or (
        lambda: ModeloLLMSDK(registro=registro_coste, al_recibir_fragmento=lambda _t: None)
    )
    # Un solo agente compartido: si llegan dos preguntas a la vez se
    # mezclarían en la conversación. El candado deja pasar de una en una.
    candado = threading.Lock()
    # Qué modo está activo. Lo guardamos al cambiar de modelo en vez de
    # deducirlo del tipo del objeto (más fiable y fácil de testear).
    activo = {"modelo": nombre_corto(agente.modelo)}

    def coste_total() -> dict[str, float] | None:
        return registro_coste.resumen() if registro_coste else None

    def titulo_de(conversacion: Conversacion) -> str:
        personalizado = repositorio.titulo(conversacion.id)
        if personalizado:
            return personalizado
        for mensaje in conversacion.get_mensajes():
            if mensaje.rol == "usuario":
                return " ".join(mensaje.contenido.split())[:60]
        return "Nueva conversación"

    # ------------------------------------------------------------ páginas --
    @app.get("/")
    def inicio() -> str:
        return render_template("index.html")

    @app.get("/metricas")
    def pagina_metricas() -> str:
        return render_template("metricas.html")

    @app.get("/api/estado")
    def estado():
        return jsonify(
            modelo=activo["modelo"],
            id=agente.conversacion.id,
            titulo=titulo_de(agente.conversacion),
            mensajes=[m.to_dict() for m in agente.conversacion.get_mensajes()],
            coste=coste_total(),
        )

    @app.post("/api/modelo")
    def cambiar_modelo():
        nombre = (request.get_json(silent=True) or {}).get("modelo")
        if nombre not in fabricas:
            return jsonify(error=f"Modelo desconocido: {nombre}"), 400
        try:
            modelo = fabricas[nombre]()
        except ErrorAgente as error:  # p. ej. falta LLM_API_KEY
            return jsonify(error=str(error)), 400
        # No cambiamos el modelo a mitad de una respuesta.
        if not candado.acquire(blocking=False):
            return jsonify(error=OCUPADO), 409
        try:
            agente.cambiar_modelo(modelo)
            activo["modelo"] = nombre
        finally:
            candado.release()
        return jsonify(modelo=nombre, detalle=getattr(modelo, "id_modelo", None))

    @app.post("/api/nueva")
    def nueva():
        if not candado.acquire(blocking=False):
            return jsonify(error=OCUPADO), 409
        try:
            agente.nueva_conversacion()
        finally:
            candado.release()
        return jsonify(ok=True)

    @app.post("/api/guardar")
    def guardar():
        try:
            return jsonify(id=repositorio.guardar(agente.conversacion))
        except OSError as error:
            return jsonify(error=str(error)), 500

    # ------------------------------------------------- historial lateral --
    @app.get("/api/conversaciones")
    def conversaciones():
        buscar = request.args.get("q", "")[:100]  # ?q=texto para buscar
        return jsonify(conversaciones=repositorio.resumenes(buscar), actual=agente.conversacion.id)

    @app.post("/api/conversaciones/<id_conv>/abrir")
    def abrir_conversacion(id_conv: str):
        if not candado.acquire(blocking=False):
            return jsonify(error=OCUPADO), 409
        try:
            agente.conversacion = repositorio.cargar(id_conv)
        except FileNotFoundError:
            return jsonify(error="Esa conversación ya no existe."), 404
        except (ValueError, ErrorAgente) as error:  # id raro, JSON roto...
            return jsonify(error=f"No se pudo abrir: {error}"), 400
        finally:
            candado.release()
        return estado()

    @app.patch("/api/conversaciones/<id_conv>")
    def editar_conversacion(id_conv: str):
        """Renombrar ({"titulo": "..."}); un título vacío vuelve al automático."""
        datos = request.get_json(silent=True) or {}
        try:
            if "titulo" in datos:
                if not isinstance(datos["titulo"], str):
                    return jsonify(error="El título debe ser texto."), 400
                repositorio.renombrar(id_conv, datos["titulo"])
        except FileNotFoundError:
            return jsonify(error="Esa conversación ya no existe."), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(ok=True)

    @app.delete("/api/conversaciones/<id_conv>")
    def borrar_conversacion(id_conv: str):
        if not candado.acquire(blocking=False):
            return jsonify(error=OCUPADO), 409
        try:
            repositorio.borrar(id_conv)
            # Si borras la que tienes abierta, empiezas una nueva.
            if agente.conversacion.id == id_conv:
                agente.nueva_conversacion()
        except FileNotFoundError:
            return jsonify(error="Esa conversación ya no existe."), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        finally:
            candado.release()
        return jsonify(ok=True, actual=agente.conversacion.id)

    # ------------------------------------------------------------ métricas --
    @app.get("/api/metricas")
    def datos_metricas():
        try:
            return jsonify(
                metricas=metricas.resumen(),
                coste=coste_total(),
                valoraciones=valoraciones.resumen(),
            )
        except (OSError, ValueError) as error:
            return jsonify(error=str(error)), 500

    @app.post("/api/valoracion")
    def valorar():
        """Un 👍 (1) o un 👎 (-1) a una respuesta de "reglas" o de "ia"."""
        datos = request.get_json(silent=True) or {}
        valor = datos.get("valor")
        # isinstance(True, int) es verdadero en Python: excluimos los booleanos.
        if isinstance(valor, bool) or valor not in (1, -1):
            return jsonify(error="valor debe ser 1 o -1."), 400
        try:
            valoraciones.registrar(str(datos.get("conversacion", ""))[:8], str(datos.get("fuente")), valor)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except OSError as error:
            return jsonify(error=f"No se pudo guardar: {error}"), 500
        return jsonify(ok=True)

    # ------------------------------------------------------- Rayos X / Lab --
    @app.post("/api/tokens")
    def tokens():
        """Parte uno o varios textos en tokens BPE reales."""
        textos = (request.get_json(silent=True) or {}).get("textos")
        if not isinstance(textos, list) or not 0 < len(textos) <= 40 or not all(isinstance(t, str) for t in textos):
            return jsonify(error="Envía una lista 'textos' (de 1 a 40)."), 400
        try:
            return jsonify(resultados=[tokenizador(t[:8000]) for t in textos])
        except ErrorAgente as error:
            return jsonify(error=str(error)), 503

    @app.post("/api/laboratorio")
    def laboratorio():
        """Lanza la MISMA pregunta varias veces con la temperatura elegida,
        en paralelo, para ver cuánto cambian las respuestas."""
        datos = request.get_json(silent=True) or {}
        pregunta = datos.get("pregunta")
        if not isinstance(pregunta, str) or not pregunta.strip() or len(pregunta) > 500:
            return jsonify(error="Escribe una pregunta (máximo 500 caracteres)."), 400
        veces = datos.get("veces", 3)
        if not isinstance(veces, int) or not 1 <= veces <= 3:
            return jsonify(error="veces debe ser 1, 2 o 3."), 400
        try:
            temperature = float(datos.get("temperature", 0.7))
        except (TypeError, ValueError):
            return jsonify(error="temperature debe ser un número."), 400

        mensajes = [
            {"role": "system", "content": ModeloLLM.PROMPT_SISTEMA},
            {"role": "user", "content": pregunta.strip()},
        ]

        def una_vez(_: int) -> dict:
            modelo = fabrica_laboratorio()  # uno por hilo: no comparten estado
            inicio = perf_counter()
            texto = modelo.preguntar(mensajes, temperature=temperature)
            uso = modelo.ultimo_uso or {}
            return {
                "texto": texto,
                "ms": round((perf_counter() - inicio) * 1000),
                "tokens": uso.get("output_tokens", 0),
                "coste": uso.get("coste", 0.0),
                "estimado": uso.get("estimado", False),
            }

        try:
            with ThreadPoolExecutor(max_workers=veces) as hilos:
                resultados = list(hilos.map(una_vez, range(veces)))
        except ErrorAgente as error:  # sin clave, temperatura fuera de rango...
            return jsonify(error=str(error)), 400
        return jsonify(
            resultados=resultados,
            parecido=parecido([r["texto"] for r in resultados]),
            coste=coste_total(),
        )

    # -------------------------------------------------------------- chat --
    @app.post("/api/chat")
    def chat():
        texto = (request.get_json(silent=True) or {}).get("mensaje")
        if not isinstance(texto, str) or not texto.strip():
            return jsonify(error="El mensaje está vacío."), 400
        if len(texto) > MAX_CARACTERES:
            return jsonify(error=f"Máximo {MAX_CARACTERES} caracteres."), 400
        if not candado.acquire(blocking=False):
            return jsonify(error=OCUPADO), 409

        cola: queue.Queue[dict | None] = queue.Queue()
        threading.Thread(target=trabajar, args=(texto.strip(), cola), daemon=True).start()
        return Response(emitir(cola), mimetype="application/x-ndjson")

    def trabajar(texto: str, cola: queue.Queue) -> None:
        """Se ejecuta en otro hilo: pregunta al agente y mete eventos en la cola."""
        try:
            modelo = agente.modelo
            ya_habia = len(agente.conversacion)
            en_streaming = getattr(modelo, "hace_streaming", False)
            if en_streaming:
                modelo.ultimo_uso = None
                # Cada trozo que llegue va directo a la cola.
                modelo.al_recibir_fragmento = lambda trozo: cola.put({"tipo": "fragmento", "texto": trozo})
            inicio = perf_counter()
            respuesta = agente.procesar(texto)
            ms = (perf_counter() - inicio) * 1000

            # Enseñamos qué herramientas usó el agente (calculadora, FAQ...).
            # El navegador las coloca ENCIMA de la respuesta.
            for mensaje in agente.conversacion.get_mensajes()[ya_habia:]:
                if mensaje.rol == "herramienta":
                    cola.put({"tipo": "herramienta", "texto": mensaje.contenido})
            if not en_streaming:
                cola.put({"tipo": "fragmento", "texto": respuesta})

            # Guardado automático y métricas. Si fallan, la respuesta ya se
            # dio, así que solo avisamos.
            uso = getattr(modelo, "ultimo_uso", None) or {}
            try:
                repositorio.guardar(agente.conversacion)
                metricas.registrar(
                    agente.conversacion.id,
                    fuente_de(modelo),
                    ms,
                    int(uso.get("output_tokens", 0)),
                    float(uso.get("coste", 0.0)),
                )
            except (OSError, ValueError) as error:
                cola.put({"tipo": "aviso", "mensaje": f"No se pudo guardar: {error}"})

            cola.put(
                {
                    "tipo": "fin",
                    "conversacion": agente.conversacion.id,
                    "titulo": titulo_de(agente.conversacion),
                    "ms": round(ms),
                    "uso": getattr(modelo, "ultimo_uso", None),
                    "coste": coste_total(),
                    # Quién respondió: reglas de NEXO o la IA (y con qué).
                    "fuente": getattr(modelo, "ultima_fuente", None),
                    # Modo activo de verdad: si el servidor se reinició, la
                    # página podría creer que está en otro.
                    "modelo": activo["modelo"],
                }
            )
        except (ErrorAgente, OSError, ValueError) as error:
            cola.put({"tipo": "error", "mensaje": str(error)})
        finally:
            cola.put(None)  # señal de "ya no hay más"
            candado.release()

    def emitir(cola: queue.Queue) -> Iterator[str]:
        """Generador que Flask va enviando al navegador según produce líneas.

        Formato NDJSON: un objeto JSON por línea, p. ej.
            {"tipo": "fragmento", "texto": "Hola"}
            {"tipo": "fin", "uso": {...}}
        """
        while (evento := cola.get()) is not None:
            yield json.dumps(evento, ensure_ascii=False) + "\n"

    return app
