# NEXO

Asistente de atención al cliente de TechNova, organizado por capas, con
**interfaz web** (Flask) y de consola.

En la web el usuario **no elige modelo**: NEXO (`ModeloHibrido`) intenta
primero responder con sus **reglas** (FAQ, calculadora, conversor: gratis,
instantáneo y sin inventar nada) y, **solo si no saben**, pasa la pregunta a
la **IA** por el SDK, indicándolo debajo de la respuesta
("✨ Respondido con IA · SDK OpenAI · openai/gpt-oss-20b · 204 tokens").

Por dentro hay cinco "cerebros" intercambiables: `ModeloEco`, `ModeloReglas`,
**`ModeloLLM`** (LLM con peticiones HTTP hechas a mano con httpx),
**`ModeloLLMSDK`** (el mismo LLM con el SDK oficial de OpenAI) y
**`ModeloHibrido`** (reglas + IA).

## Núcleo (lo que pide la actividad)

- Nivel 2: agente, herramientas, modelos de reglas, chat de consola y
  persistencia de conversaciones (JSON) y uso de herramientas (CSV).
- **Nivel 3, `ModeloLLM`**:
  - clave en `.env` (nunca en el código) leída con `python-dotenv`,
  - validación de la petición antes de enviarla,
  - reintentos con `tenacity` (espera exponencial 1-2-4-8 s, máximo 5 intentos)
    **solo** para 429, 5xx y errores de red,
  - streaming real (SSE) mostrado trozo a trozo,
  - registro de tokens y coste en `datos/uso_llm.csv`.
- **`ModeloLLMSDK`**: misma funcionalidad con el SDK `openai`. Hereda de
  `ModeloLLM` y solo reescribe el método que habla con la red (`_eventos`).
- **`ModeloHibrido`**: reglas primero, IA solo si las reglas no saben.
- **La IA conoce los datos de TechNova**: el prompt del sistema lleva las FAQ
  reales de la tienda y la orden de **no inventar** lo que no sepa (precios,
  stock, tiendas, contactos...), sino remitir a atención al cliente. Es una
  versión mínima de RAG: dar contexto al modelo dentro del prompt. Cuesta unos
  tokens de entrada más en cada llamada. Reduce las invenciones, pero **no las
  elimina**.
- **`MemoriaHistorial`: NEXO recuerda tus conversaciones.** El historial no es
  solo una pantalla: es una **herramienta del agente**, como la calculadora.
  Pregúntale *«¿qué me dijiste del envío ayer?»* o *«¿de qué hablamos la
  semana pasada?»* y busca en tus conversaciones guardadas (por palabras y por
  fecha). La resuelven las reglas: gratis, sin IA y sin inventar nada. Recibe
  su fuente de datos por inyección de dependencias, así el dominio no sabe de
  archivos.
- **Interfaz web** en el navegador: chat con streaming, etiqueta de quién
  respondió (reglas o IA, con tokens, coste y tiempo), herramientas usadas
  visibles y diseño adaptado a móvil.
- **Comparación reglas frente a IA**: `comparar_modelos.py` y el panel de
  métricas (`/metricas`): € ahorrados gracias a las reglas, % resuelto sin IA,
  velocidad, tokens por día y últimas respuestas.
- **👍 / 👎 en cada respuesta**: se guarda quién respondió (reglas o IA) en
  `datos/valoraciones.csv` y el panel muestra el % de 👍 de cada uno, es decir,
  la comparación reglas frente a IA según la opinión del usuario.
- 114 tests sin conexión a internet (`test_modelo.py`, `test_hibrido.py`,
  `test_web.py`, `test_extras.py` y `test_memoria.py`).

## Extras

- **🔊 Escuchar (solo en el móvil)**: cada respuesta nueva tiene un botón que
  la lee en voz alta con la voz del propio navegador (`speechSynthesis`). Para
  dictar se usa el micrófono del teclado del móvil.
- **📱 Acceso desde el móvil con HTTPS**: `python web.py --movil` abre NEXO a
  los aparatos de tu misma red por una conexión **cifrada**. El certificado es
  autofirmado, así que el móvil avisa de que «la conexión no es privada»
  (Configuración avanzada → Continuar). Además pide un **código de acceso** de
  6 cifras, nuevo en cada arranque, que sale en la terminal (se bloquea tras 5
  fallos; tu ordenador no lo necesita). Es un código compartido, no cuentas de
  usuario: úsalo solo en tu casa o en tu propio punto de acceso.
- **Dos temas**: *Crema* (beige TechNova con acento coñac) y *Espresso*
  (marrones oscuros con acento caramelo). Se recuerda tu elección.
- **🔬 Rayos X (Tema 2)**: cada mensaje muestra sus **tokens BPE reales**
  (`tiktoken`, codificación `o200k_base`) coloreados, comparados con nuestra
  estimación palabras × 1,3, y los **tokens de razonamiento oculto** que la
  API cobra pero no se ven.
- **🧪 Laboratorio de temperatura**: la misma pregunta 3 veces en paralelo con
  la **temperature** que elijas, y el % de parecido entre las respuestas
  (temperatura 0 → 100 %; 1,5 → ~15 %).
- **Historial lateral**: se guarda solo; icono según el **tema detectado**
  (📦 envíos, 💳 pagos, 💻 tecnología…), **renombrar** (doble clic) y
  **buscar en todos los mensajes** con el texto resaltado. Atajos: `Alt+N`
  nueva, `/` buscar.

> La versión completa, con voz, informe PDF y laboratorio con top-p, está en
> la carpeta `nexo`. Esta (`nexo-clase`) es la versión más sencilla para
> entregar.

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # .env clave
```

`.env` y `datos/` están en `.gitignore`: con `git`, ni la clave ni las
conversaciones se suben a GitHub. Solo se sube `.env.example`, que sirve de
plantilla sin la clave. La carpeta `datos/` se crea sola al usar la app.

Cualquier proveedor compatible con OpenAI funciona cambiando `LLM_API_URL` y
`LLM_MODEL` en `.env` (ver ejemplos de OpenAI, Groq y Ollama en `.env.example`).

## Ejecutar

```powershell
python web.py                      # chat en el navegador (http://127.0.0.1:5000)
python web.py --movil              # también desde el móvil, cifrado (https)
python main.py                     # chat en la consola
python comparar_modelos.py         # 10 preguntas a           ModeloReglas y ModeloLLM
python -m unittest test_modelo.py test_hibrido.py test_web.py test_extras.py test_memoria.py -v
```

`python web.py` abre el navegador solo. Para parar el servidor, `Ctrl + C` en
la terminal. El modo eco está en la palabra «eco», muy discreta, junto al pie
de la página.

Comandos del chat de consola: `/help`, `/herramientas`, `/modelo nexo|eco|reglas|llm|sdk`,
`/historial`, `/guardar`, `/cargar <id>`, `/lista`, `/nueva`, `/stats`,
`/coste` y `/salir`.

Uso de `ModeloLLM` desde Python, como en el enunciado (lee `.env`, muestra el
streaming y registra en `datos/uso_llm.csv`):

```python
from dominio.modelos import ModeloLLM
ModeloLLM().preguntar([{"role": "user", "content": "¿Qué es un SSD?"}])
```

### Ejemplo de salida

Fragmento real de `python comparar_modelos.py` (27/11/2026):

```text
[1/10] ¿Cuánto tarda el envío?
   REGLAS (    0.3 ms): Los envíos tardan 24-48 h en península y 3-5 días en islas. ¿Necesitas algo más?
   LLM    (  428.0 ms, 49 tokens): Los envíos tardan entre 24 y 48 h en la península y de 3 a 5 días en las islas.

[4/10] calcula 15 * 4
   REGLAS (    0.1 ms): 15 * 4 = 60. ¿Necesitas algo más?
   LLM    (  514.9 ms, 23 tokens): 15 * 4 = 60.
======================================================================
Tiempo medio  · reglas:     0.34 ms   · LLM:   468.45 ms
Sin respuesta · reglas: 3/10   · errores LLM: 0/10
Tokens LLM: 788 · coste LLM: 0.006304 € · tokens reglas: 0 · coste reglas: 0 €
```

Registro en `datos/uso_llm.csv`:

```text
timestamp,question,output_tokens,cost
2026-11-27T09:39:09,¿Cuánto tarda el envío?,49,0.000392
2026-11-27T09:39:11,calcula 15 * 4,23,0.000184
```

Coste = `output_tokens × 0,008 / 1000` € (fórmula del material [3]).
49 × 0,008 / 1000 = 0,000392 € ✔

Tests:

```text
Ran 114 tests in 4.6s
OK
```

## Estructura

```text
nexo/
├── web.py                     arranca la interfaz web (carga .env)
├── main.py                    arranca el chat de consola (carga .env)
├── comparar_modelos.py        paso 4: reglas vs LLM
├── test_modelo.py             tests de ModeloLLM y ModeloLLMSDK
├── test_hibrido.py            tests de ModeloHibrido
├── test_web.py                tests de la interfaz web
├── test_extras.py             tests de temas, métricas, Rayos X y laboratorio
├── test_memoria.py            tests de la memoria del historial, 👍/👎 y el prompt con datos
├── dominio/
│   ├── modelos.py             ModeloEco, ModeloReglas, ModeloLLM (httpx), validar_peticion
│   ├── modelo_sdk.py          ModeloLLMSDK (SDK oficial de OpenAI)
│   ├── modelo_hibrido.py      ModeloHibrido: reglas primero, IA si no saben
│   ├── tokenizador.py         tokens BPE reales con tiktoken (Rayos X)
│   ├── temas.py               detecta el tema de una conversación (icono)
│   ├── excepciones.py         + PeticionInvalida, ErrorProveedorLLM
│   ├── herramientas.py        calculadora, conversor, FAQ y MemoriaHistorial
│   └── mensaje.py
├── servicios/agente.py
├── persistencia/
│   ├── registro_uso.py        uso de herramientas  -> datos/uso.csv
│   ├── registro_coste.py      tokens y coste LLM    -> datos/uso_llm.csv
│   ├── registro_metricas.py   cada respuesta (reglas/IA, ms, tokens) -> datos/metricas.csv
│   ├── registro_valoraciones.py  👍/👎 de cada respuesta -> datos/valoraciones.csv
│   └── repositorio_conversaciones.py
└── presentacion/
    ├── chat_consola.py        interfaz de consola
    ├── web.py                 interfaz web (Flask): rutas /api/...
    ├── acceso.py              código de acceso del modo móvil
    ├── templates/             index.html (chat), metricas.html y acceso.html
    └── static/                estilo.css (temas), chat.js, metricas.js
```

La web y la consola usan **el mismo** `Agente` y los mismos modelos: solo
cambia la capa de presentación. Esa es la ventaja de separar por capas.

## Decisiones de diseño

1. **Coste en `uso_llm.csv` y no en `uso.csv`.** `uso.csv` ya existe con las
   columnas de herramientas, y `RegistroUso.resumen()` falla si la cabecera no
   coincide. Mezclar dos formatos en un mismo CSV rompería `/stats`.
2. **Solo se reintentan 429, 5xx y errores de red.** Un 400 o un 401 es culpa
   de la petición o de la clave: repetirlo da el mismo error y malgasta cuota.
3. **Solo se reintenta la apertura de la conexión.** Si la red se corta a mitad
   de respuesta no se repite, porque parte del texto ya se mostró y se duplicaría.
4. **Tokens reales.** Se pide `stream_options.include_usage` para que la API
   diga los tokens de verdad. Si el proveedor no lo da, se estima (palabras ×
   1,3, la misma regla que `Conversacion.tokens_estimados()`).
5. **Se registra la última pregunta del usuario**, no `mensajes[0]` (que en una
   conversación larga sería la primera).
6. **Inyección de dependencias.** `ModeloLLM` recibe el registro y el cliente
   HTTP desde fuera, y los tests pueden usar un servidor falso
   (`httpx.MockTransport`). Única excepción a «el dominio no depende de la
   persistencia»: si se crea `ModeloLLM()` sin clave ni registro, como en el
   enunciado, carga `.env` y usa el registro CSV por defecto (el import está
   dentro de una función).
7. **La clave no aparece nunca** en el código, en `repr(modelo)` ni en los
   mensajes de error. La clave tampoco llega nunca al navegador: solo la usa
   el servidor Python.
8. **httpx y SDK, los dos.** El enunciado pide httpx + tenacity; el SDK se
   añade como alternativa. En el SDK se desactivan sus reintentos propios
   (`max_retries=0`) para usar la misma política de tenacity y poder comparar.
9. **Web segura.** El texto se pinta con `textContent` (nunca `innerHTML`),
   así que un `<script>` en una respuesta no se ejecuta (evita XSS). El
   servidor escucha solo en `127.0.0.1`, limita los mensajes a 2000 caracteres
   y no deja cambiar de modelo mientras se está respondiendo.

## Si se bloquea

| Síntoma | Causa probable |
| --- | --- |
| `Falta LLM_API_KEY` | No existe `.env` o está en otra carpeta |
| `[HTTP 401]` | Clave incorrecta o caducada |
| `[HTTP 400]` | Nombre de modelo incorrecto o JSON mal formado: prueba a bajar `max_tokens` |
| `[HTTP 404]` | `LLM_API_URL` o `LLM_MODEL` mal escritos |
| `[HTTP 429]` tras 5 intentos | Sin saldo o límite de la cuenta gratuita |
| `[HTTP 404]` "model does not exist" | El proveedor retiró ese modelo: Groq retiró `llama-3.1-8b-instant`; ahora se usa `openai/gpt-oss-20b` |
| Respuestas vacías o cortadas con `gpt-oss` | Es un modelo que razona en secreto y gasta `max_tokens` pensando: poner `LLM_REASONING_EFFORT=low` en `.env` |


## Uso de asistentes de IA

Partiendo de mi proyecto, usé un asistente de IA (Claude) para escribir el código nuevo, las pruebas automáticas y la documentación. Yo decidí qué cosas mejorar o quitar y cómo quería que funcionase. Probé las respuestas de las reglas y de la IA, el funcionamiento general y el uso desde el móvil, y comprobé que las reglas seguían funcionando.

## Reflexión

**¿Cuándo usaría reglas y cuándo IA?** Usaría las reglas para las cosas clave de la tienda, como los envíos y los pagos. La IA quizá la usaría para las descripciones, por ejemplo para contar qué características tiene un ordenador de la tienda, dándole antes sus datos para que no se los invente.

**¿Qué respuesta de la IA me llamó la atención?** La del portátil, porque mezcló la recomendación del ordenador con información de la web y de la compra, que no le había pedido.

**¿Qué he aprendido?** Ahora entiendo mucho mejor cómo funcionan las reglas, cómo funciona un LLM y qué son los tokens. Todavía me falta afianzar un poco la estructura del proyecto.

**¿Qué me costó más?** Conseguir que NEXO funcionara en el móvil y que fuera seguro.

**¿Qué mejoraría?** Haría que NEXO entendiera las palabras por su significado, y no solo cuando coinciden con las que tiene guardadas.

