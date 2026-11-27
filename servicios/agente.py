from dominio.excepciones import ArgumentosInvalidos, ErrorAgente, HerramientaNoEncontrada
from dominio.herramientas import Herramienta
from dominio.mensaje import Conversacion, Mensaje
from dominio.modelos import Modelo
from time import perf_counter


class Agente:
    MAX_LLAMADAS_HERRAMIENTA = 3

    def __init__(
        self,
        modelo: Modelo,
        herramientas: list[Herramienta],
        registro_uso: object | None = None,
    ) -> None:
        self.modelo = modelo
        self._herramientas = {herramienta.nombre: herramienta for herramienta in herramientas}
        self._registro = registro_uso
        self.conversacion = Conversacion()

    def procesar(self, texto_usuario: str) -> str:
        self.conversacion.agregar(Mensaje("usuario", texto_usuario))
        llamadas = 0

        while True:
            respuesta = self.modelo.responder(
                self.conversacion, list(self._herramientas.values())
            )
            if not respuesta.es_llamada_herramienta():
                if respuesta.texto is None:
                    raise ErrorAgente("El modelo no proporcionó una respuesta.")
                self.conversacion.agregar(Mensaje("asistente", respuesta.texto))
                return respuesta.texto

            nombre = respuesta.herramienta
            herramienta = self._herramientas.get(nombre)
            if herramienta is None:
                raise HerramientaNoEncontrada(
                    f"No existe la herramienta solicitada: {nombre}"
                )
            if llamadas >= self.MAX_LLAMADAS_HERRAMIENTA:
                raise ErrorAgente("Se alcanzó el límite de llamadas a herramientas.")

            try:
                inicio = perf_counter()
                resultado = herramienta.ejecutar(**respuesta.argumentos)
            except ArgumentosInvalidos as error:
                milisegundos = (perf_counter() - inicio) * 1000
                resultado = f"Error: {error}"
                self._registrar_uso(
                    herramienta,
                    respuesta.argumentos,
                    False,
                    str(error),
                    milisegundos,
                )
            else:
                milisegundos = (perf_counter() - inicio) * 1000
                self._registrar_uso(
                    herramienta,
                    respuesta.argumentos,
                    True,
                    "",
                    milisegundos,
                )

            self.conversacion.agregar(Mensaje("herramienta", resultado))
            llamadas += 1

    def _registrar_uso(
        self,
        herramienta: Herramienta,
        argumentos: dict[str, object],
        exito: bool,
        error: str,
        milisegundos: float,
    ) -> None:
        if self._registro is not None:
            registrar = getattr(self._registro, "registrar", None)
            if callable(registrar):
                registrar(
                    herramienta.nombre,
                    argumentos,
                    exito,
                    error,
                    milisegundos,
                )

    def listar_herramientas(self) -> list[str]:
        return [
            f"{herramienta.nombre}: {herramienta.descripcion}"
            for herramienta in self._herramientas.values()
        ]

    def cambiar_modelo(self, modelo: Modelo) -> None:
        self.modelo = modelo

    def nueva_conversacion(self) -> None:
        self.conversacion = Conversacion()