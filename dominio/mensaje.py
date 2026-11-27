from datetime import datetime
from uuid import uuid4

from .excepciones import LimiteContextoSuperado


class Mensaje:
    """Mensaje individual dentro de una conversación."""

    ROLES_VALIDOS = {"usuario", "asistente", "herramienta"}

    def __init__(
        self, rol: str, contenido: str, fecha: str | None = None
    ) -> None:
        if rol not in self.ROLES_VALIDOS:
            raise ValueError(f"Rol no válido: {rol}")
        if not isinstance(contenido, str):
            raise TypeError("El contenido del mensaje debe ser texto.")
        self.rol = rol
        self.contenido = contenido
        self.fecha = fecha or datetime.now().isoformat()

    def __str__(self) -> str:
        return f"[{self.rol}] {self.contenido}"

    def to_dict(self) -> dict[str, str]:
        return {
            "rol": self.rol,
            "contenido": self.contenido,
            "fecha": self.fecha,
        }

    @classmethod
    def from_dict(cls, datos: dict[str, str]) -> "Mensaje":
        return cls(datos["rol"], datos["contenido"], datos["fecha"])


class Conversacion:
    """Historial encapsulado de mensajes con un límite de contexto estimado."""

    # 4000 en vez de 500: con respuestas del LLM de hasta 300 tokens, 500 se
    # superaba en la segunda pregunta. Los modelos de Groq admiten 131 072.
    def __init__(self, id: str | None = None, limite_tokens: int = 4000) -> None:
        if limite_tokens < 0:
            raise ValueError("El límite de tokens no puede ser negativo.")
        self.id = id or uuid4().hex[:8]
        self.__mensajes: list[Mensaje] = []
        self._limite_tokens = limite_tokens

    def agregar(self, mensaje: Mensaje) -> None:
        if not isinstance(mensaje, Mensaje):
            raise TypeError("Solo se pueden agregar objetos Mensaje.")
        self.__mensajes.append(mensaje)
        if self.tokens_estimados() > self._limite_tokens:
            self.__mensajes.pop()
            raise LimiteContextoSuperado(
                f"La conversación supera el límite de {self._limite_tokens} tokens."
            )

    def get_mensajes(self) -> list[Mensaje]:
        return self.__mensajes.copy()

    def tokens_estimados(self) -> int:
        total_palabras = sum(
            len(mensaje.contenido.split()) for mensaje in self.__mensajes
        )
        return round(total_palabras * 1.3)

    def __len__(self) -> int:
        return len(self.__mensajes)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "mensajes": [mensaje.to_dict() for mensaje in self.__mensajes],
        }

    @classmethod
    def from_dict(cls, datos: dict[str, object]) -> "Conversacion":
        conversacion = cls(id=str(datos["id"]))
        for mensaje in datos["mensajes"]:
            conversacion.agregar(Mensaje.from_dict(mensaje))
        return conversacion