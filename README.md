# NEXO

Asistente de atención al cliente de TechNova, organizado por capas, con
interfaz web y de consola. Primero responden las **reglas** (gratis y exactas)
y, solo si no saben, la **IA**.

## Qué incluye

- **`ModeloLLM`** (httpx): clave en `.env`, validación de la petición,
  reintentos con `tenacity` (429, 5xx y errores de red, máximo 5), streaming y
  registro de tokens y coste en `datos/uso_llm.csv`.
- **`ModeloLLMSDK`**: lo mismo con el SDK de OpenAI.
- **`ModeloReglas`** y **`ModeloHibrido`** (reglas primero, IA después).
- **Web**: historial con memoria (*«¿qué me dijiste del envío?»*), valoración
  👍/👎, panel de métricas, tokens a la vista, laboratorio de temperatura y dos
  temas.
- **Móvil**: HTTPS y código de acceso.

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Escribe tu clave en `.env`. En `.env.example` hay ejemplos para OpenAI, Groq y
Ollama.

## Ejecutar

```powershell
python web.py                 # web en http://127.0.0.1:5000
python web.py --movil         # también desde el móvil (misma red)
python main.py                # consola
python comparar_modelos.py    # 10 preguntas a ModeloReglas y ModeloLLM
python -m unittest test_modelo.py test_hibrido.py test_web.py test_extras.py test_memoria.py
```

## Ejemplo de salida

`python comparar_modelos.py` (fragmento real):

```text
[1/10] ¿Cuánto tarda el envío?
   REGLAS (    0.3 ms): Los envíos tardan 24-48 h en península y 3-5 días en islas. ¿Necesitas algo más?
   LLM    (  428.0 ms, 49 tokens): Los envíos tardan entre 24 y 48 h en la península y de 3 a 5 días en las islas.
======================================================================
Tiempo medio  · reglas:     0.34 ms   · LLM:   468.45 ms
Sin respuesta · reglas: 3/10   · errores LLM: 0/10
Tokens LLM: 788 · coste LLM: 0.006304 € · tokens reglas: 0 · coste reglas: 0 €
```

`datos/uso_llm.csv` (coste = tokens de salida × 0,008 / 1000 €):

```text
timestamp,question,output_tokens,cost
2026-11-27T09:39:09,¿Cuánto tarda el envío?,49,0.000392
```

Tests: `Ran 114 tests ... OK`

## Estructura

| Carpeta | Contiene |
| --- | --- |
| `dominio/` | Modelos, herramientas y conversación |
| `servicios/` | El agente |
| `persistencia/` | Conversaciones (JSON) y registros (CSV) |
| `presentacion/` | Consola y web (Flask) |
