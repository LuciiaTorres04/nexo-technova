class ErrorAgente(Exception):
    """Excepción base de los errores controlados de NEXO."""


class HerramientaNoEncontrada(ErrorAgente):
    """Se solicita una herramienta que no está registrada."""


class ArgumentosInvalidos(ErrorAgente):
    """Los argumentos de una herramienta no son válidos."""


class LimiteContextoSuperado(ErrorAgente):
    """La conversación superaría el límite estimado de tokens."""


class PeticionInvalida(ErrorAgente, ValueError):
    """La petición al LLM no cumple las reglas y ni siquiera se envía.

    Hereda también de ValueError porque, conceptualmente, es un valor
    incorrecto (igual que en el ejemplo del enunciado).
    """


class ErrorProveedorLLM(ErrorAgente):
    """El proveedor del LLM falló o no está bien configurado (clave, URL...)."""