from dominio.excepciones import ErrorAgente
from dominio.modelo_hibrido import crear_modelo_nexo
from dominio.modelo_sdk import ModeloLLMSDK
from dominio.modelos import Modelo, ModeloEco, ModeloLLM, ModeloReglas
from persistencia.registro_coste import RegistroCosteLLM
from persistencia.registro_uso import RegistroUso
from persistencia.repositorio_conversaciones import RepositorioConversaciones
from servicios.agente import Agente


class ChatConsola:
    def __init__(
        self,
        agente: Agente,
        repositorio: RepositorioConversaciones | None = None,
        registro_uso: RegistroUso | None = None,
        registro_coste: RegistroCosteLLM | None = None,
    ) -> None:
        self.agente = agente
        self.repositorio = repositorio or RepositorioConversaciones()
        self.registro_uso = registro_uso or getattr(agente, "_registro", None)
        self.registro_coste = registro_coste

    def iniciar(self) -> None:
        print("╭──────────────────────────────────────╮")
        print("│  🤖  NEXO · asistente de TechNova    │")
        print("│  Escribe /help para ver los comandos │")
        print("╰──────────────────────────────────────╯")
        while True:
            try:
                entrada = input("tú   > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not entrada:
                continue
            if entrada == "/salir":
                return
            if entrada in {"/help", "/ayuda"}:
                self._mostrar_ayuda()
                continue
            if entrada == "/herramientas":
                for herramienta in self.agente.listar_herramientas():
                    print(f"• {herramienta}")
                continue
            if entrada.startswith("/modelo"):
                self._cambiar_modelo(entrada)
                continue
            if entrada == "/historial":
                self._mostrar_historial()
                continue
            if entrada == "/guardar":
                self._guardar()
                continue
            if entrada.startswith("/cargar"):
                self._cargar(entrada)
                continue
            if entrada == "/lista":
                self._listar()
                continue
            if entrada == "/nueva":
                self.agente.nueva_conversacion()
                print("✔ Conversación nueva.")
                continue
            if entrada == "/stats":
                self._mostrar_estadisticas()
                continue
            if entrada == "/coste":
                self._mostrar_coste()
                continue
            self._responder(entrada)

    def _responder(self, entrada: str) -> None:
        # Con streaming, el modelo imprime el texto él mismo mientras llega:
        # aquí solo ponemos el prefijo antes y el salto de línea después.
        en_streaming = getattr(self.agente.modelo, "hace_streaming", False)
        if en_streaming:
            print("NEXO > ", end="", flush=True)
        try:
            texto = self.agente.procesar(entrada)
        except (ErrorAgente, OSError, ValueError) as error:
            prefijo = "\n       " if en_streaming else "NEXO > "
            print(f"{prefijo}No he podido completar la petición: {error}")
            return
        if en_streaming:
            print()  # el texto ya está en pantalla; solo cerramos la línea
        else:
            print(f"NEXO > {texto}")

    @staticmethod
    def _mostrar_ayuda() -> None:
        print(
            "Comandos disponibles:\n"
            "  /help, /ayuda       Muestra esta ayuda\n"
            "  /herramientas       Lista las herramientas\n"
            "  /modelo nexo|eco|reglas|llm|sdk  Cambia el modelo (nexo = reglas + IA)\n"
            "  /historial          Muestra mensajes y tokens estimados\n"
            "  /guardar            Guarda la conversación actual\n"
            "  /cargar <id>        Carga una conversación guardada\n"
            "  /lista              Lista las conversaciones guardadas\n"
            "  /nueva              Empieza una conversación nueva\n"
            "  /stats              Muestra el resumen de uso de herramientas\n"
            "  /coste              Muestra tokens y coste acumulado del LLM\n"
            "  /salir              Termina el programa"
        )

    def _mostrar_historial(self) -> None:
        for mensaje in self.agente.conversacion.get_mensajes():
            print(mensaje)
        print(f"Tokens estimados: {self.agente.conversacion.tokens_estimados()}")

    def _guardar(self) -> None:
        id_conv = self.repositorio.guardar(self.agente.conversacion)
        print(f"💾 Conversación {id_conv} guardada.")

    def _cargar(self, entrada: str) -> None:
        partes = entrada.split()
        if len(partes) != 2 or partes[0] != "/cargar":
            print("Uso: /cargar <id>")
            return
        self.agente.conversacion = self.repositorio.cargar(partes[1])
        print(f"✔ Conversación {partes[1]} cargada.")

    def _listar(self) -> None:
        ids = self.repositorio.listar()
        if not ids:
            print("No hay conversaciones guardadas.")
            return
        for id_conv in ids:
            print(id_conv)

    def _mostrar_estadisticas(self) -> None:
        if self.registro_uso is None:
            print("El registro de uso no está configurado.")
            return
        resumen = self.registro_uso.resumen()
        if not resumen:
            print("Todavía no hay usos registrados.")
            return
        for herramienta, usos in resumen.items():
            if herramienta == "fallos":
                continue
            print(f"{herramienta}: {usos} uso(s)")
        print(f"Fallos: {resumen.get('fallos', 0)}")

    def _mostrar_coste(self) -> None:
        if self.registro_coste is None:
            print("El registro de coste no está configurado.")
            return
        resumen = self.registro_coste.resumen()
        print(
            f"Respuestas del LLM: {resumen['respuestas']} · "
            f"tokens de salida: {resumen['tokens']} · "
            f"coste total: {resumen['coste']:.6f} €"
        )

    def _cambiar_modelo(self, entrada: str) -> None:
        partes = entrada.split()
        nombre = partes[1].casefold() if len(partes) == 2 else ""
        if nombre not in {"nexo", "eco", "reglas", "llm", "sdk"}:
            print("NEXO > Uso: /modelo nexo, eco, reglas, llm o sdk")
            return
        try:
            modelo: Modelo
            if nombre == "nexo":
                modelo = crear_modelo_nexo(self.registro_coste)
            elif nombre == "eco":
                modelo = ModeloEco()
            elif nombre == "reglas":
                modelo = ModeloReglas()
            elif nombre == "sdk":
                modelo = ModeloLLMSDK(registro=self.registro_coste)
            else:
                modelo = ModeloLLM(registro=self.registro_coste)
        except ErrorAgente as error:  # p. ej. falta la clave en .env
            print(f"NEXO > No puedo activar ese modelo: {error}")
            return
        self.agente.cambiar_modelo(modelo)
        detalle = f" ({modelo.id_modelo})" if isinstance(modelo, ModeloLLM) else ""
        print(f"✔ Modelo cambiado a {type(modelo).__name__}{detalle}")