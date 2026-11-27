"""ModeloHibrido: NEXO decide solo quién responde.

    pregunta ─► ModeloReglas ─┬─► sabe (FAQ, calculadora, moneda, saludo)
                              │      └─► responde las reglas: gratis, al instante,
                              │          y nunca se inventa nada
                              └─► no sabe ("No estoy seguro" / "No encontrado")
                                     └─► responde la IA (LLM): flexible, pero
                                         cuesta tokens y puede inventar

Así el usuario no tiene que elegir modelo: lo que NEXO sabe con seguridad lo
contesta con sus datos, y solo lo demás se lo pregunta a la IA.

Es una "cadena de responsabilidad" (Chain of Responsibility): la pregunta
pasa al primero; si no puede, al siguiente. Y como ModeloHibrido es también un
Modelo (mismo método responder), el Agente lo usa sin saber que por dentro
hay dos: composición + polimorfismo.
"""

from .excepciones import ErrorAgente
from .mensaje import Conversacion
from .modelo_sdk import ModeloLLMSDK
from .modelos import Modelo, ModeloLLM, ModeloReglas, Respuesta, _imprimir_fragmento

# Respuestas de las reglas que significan "no lo sé".
RESPUESTAS_SIN_SABER = (ModeloReglas.RESPUESTA_DESCONOCIDA, "No encontrado")


class ModeloHibrido(Modelo):
    # El texto siempre sale por al_recibir_fragmento (lo responda quien lo
    # responda), así la consola y la web lo tratan todo igual.
    hace_streaming = True

    def __init__(
        self,
        llm: ModeloLLM | None = None,
        reglas: ModeloReglas | None = None,
        etiqueta_llm: str = "SDK OpenAI",
    ) -> None:
        super().__init__("nexo")
        self.reglas = reglas or ModeloReglas()
        self.llm = llm  # None si no hay clave: entonces solo responden las reglas
        self.etiqueta_llm = etiqueta_llm
        self.al_recibir_fragmento = _imprimir_fragmento
        self.ultimo_uso: dict[str, object] | None = None
        # Quién respondió la última vez, para enseñarlo debajo de la respuesta.
        self.ultima_fuente: dict[str, str] | None = None

    def responder(self, conversacion: Conversacion, herramientas: list) -> Respuesta:
        respuesta = self.reglas.responder(conversacion, herramientas)

        # Las reglas piden una herramienta: se la devolvemos al Agente, que la
        # ejecuta y nos vuelve a llamar con el resultado.
        if respuesta.es_llamada_herramienta():
            return respuesta

        if not self._reglas_no_saben(respuesta.texto) or self.llm is None:
            self.ultimo_uso = None  # las reglas no gastan tokens
            self.ultima_fuente = {"tipo": "reglas", "detalle": "Reglas de NEXO"}
            self.al_recibir_fragmento(respuesta.texto)
            return respuesta

        # Las reglas no saben: se lo pasamos a la IA, que irá mandando los
        # trozos al mismo sitio (consola o navegador).
        self.llm.al_recibir_fragmento = self.al_recibir_fragmento
        self.llm.ultimo_uso = None
        respuesta_ia = self.llm.responder(conversacion, herramientas)
        self.ultimo_uso = self.llm.ultimo_uso
        self.ultima_fuente = {
            "tipo": "ia",
            "detalle": f"{self.etiqueta_llm} · {self.llm.id_modelo}",
        }
        return respuesta_ia

    @staticmethod
    def _reglas_no_saben(texto: str | None) -> bool:
        return texto is None or texto.startswith(RESPUESTAS_SIN_SABER)


def crear_modelo_nexo(registro: object | None = None) -> ModeloHibrido:
    """NEXO tal como lo usa el usuario: reglas primero y, si no saben, la IA
    por el SDK. Si no hay clave en .env, funciona solo con sus reglas."""
    try:
        llm: ModeloLLM | None = ModeloLLMSDK(registro=registro)
    except ErrorAgente:
        llm = None
    return ModeloHibrido(llm=llm)
