"""Reloj puro de preparación para hipótesis temporales. No envía órdenes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math

HORIZONTES_SEGUNDOS = frozenset((30, 60, 120, 300, 600))


class EstadoReloj(str, Enum):
    ESPERAR = "ESPERAR"
    PREPARARSE = "PREPARARSE"
    CUENTA_REGRESIVA = "CUENTA_REGRESIVA"
    ENTRAR = "ENTRAR"
    CANCELADA = "CANCELADA"
    VENTANA_CERRADA = "VENTANA_CERRADA"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Los tiempos deben ser datetime con zona horaria")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class HipotesisEntrada:
    """Una hipótesis temporal. No es una orden ni una predicción validada."""
    direccion: str
    duracion_segundos: int
    entrada_utc: datetime
    creada_utc: datetime
    validada: bool = False
    simbolo: str = "NVDA"

    def __post_init__(self) -> None:
        if self.direccion not in ("SUBE", "BAJA"):
            raise ValueError("Dirección no admitida")
        if self.duracion_segundos not in HORIZONTES_SEGUNDOS:
            raise ValueError("Horizonte no admitido")
        entrada, creada = _utc(self.entrada_utc), _utc(self.creada_utc)
        if entrada <= creada:
            raise ValueError("La entrada debe ser posterior a la detección")
        if not isinstance(self.validada, bool):
            raise ValueError("validada debe ser booleana")
        if not isinstance(self.simbolo, str) or not self.simbolo:
            raise ValueError("Símbolo vacío")
        object.__setattr__(self, "entrada_utc", entrada)
        object.__setattr__(self, "creada_utc", creada)


@dataclass(frozen=True)
class LecturaReloj:
    estado: EstadoReloj
    segundos_para_entrada: int | None
    direccion: str | None
    duracion_segundos: int | None
    entrada_utc: datetime | None
    motivo: str
    operativa_autorizada: bool = False


def evaluar_reloj(
    hipotesis: HipotesisEntrada | None,
    *,
    ahora_utc: datetime,
    ultimo_dato_utc: datetime | None = None,
    preparacion_segundos: int = 30,
    cuenta_regresiva_segundos: int = 10,
    ventana_entrada_segundos: float = 1.0,
    antiguedad_maxima_dato_segundos: float = 2.0,
    tolerancia_reloj_futuro_segundos: float = 0.5,
) -> LecturaReloj:
    """Evalúa el reloj sin efectos secundarios.

    El resultado ENTRAR indica solo el instante de una hipótesis validada
    externamente: no autoriza operar. Alpaca IEX no liquida IQ Option.
    """
    ahora = _utc(ahora_utc)
    if (preparacion_segundos <= 0 or cuenta_regresiva_segundos <= 0
            or cuenta_regresiva_segundos > preparacion_segundos
            or not math.isfinite(ventana_entrada_segundos) or ventana_entrada_segundos <= 0
            or not math.isfinite(antiguedad_maxima_dato_segundos)
            or antiguedad_maxima_dato_segundos <= 0
            or not math.isfinite(tolerancia_reloj_futuro_segundos)
            or tolerancia_reloj_futuro_segundos < 0):
        raise ValueError("Configuración temporal inválida")

    def lectura(estado: EstadoReloj, motivo: str, restante: int | None = None):
        return LecturaReloj(estado, restante,
                            hipotesis.direccion if hipotesis else None,
                            hipotesis.duracion_segundos if hipotesis else None,
                            hipotesis.entrada_utc if hipotesis else None, motivo)

    if hipotesis is None:
        return lectura(EstadoReloj.ESPERAR, "Sin hipótesis temporal")
    if not hipotesis.validada:
        return lectura(EstadoReloj.ESPERAR, "Hipótesis no validada")
    if ahora < hipotesis.creada_utc:
        return lectura(EstadoReloj.CANCELADA, "Detección posterior al reloj actual")
    if ultimo_dato_utc is None:
        return lectura(EstadoReloj.CANCELADA, "Sin marca temporal de datos de mercado")
    ultimo = _utc(ultimo_dato_utc)
    edad = (ahora - ultimo).total_seconds()
    if edad < -tolerancia_reloj_futuro_segundos:
        return lectura(EstadoReloj.CANCELADA, "Desajuste de reloj o dato del futuro")
    if edad > antiguedad_maxima_dato_segundos:
        return lectura(EstadoReloj.CANCELADA, "Datos de mercado atrasados")

    restante = (hipotesis.entrada_utc - ahora).total_seconds()
    if restante < -ventana_entrada_segundos:
        return lectura(EstadoReloj.VENTANA_CERRADA, "Instante de entrada vencido", 0)
    if restante <= 0:
        return lectura(EstadoReloj.ENTRAR, "Instante de entrada hipotético", 0)
    segundos = math.ceil(restante)
    if restante <= cuenta_regresiva_segundos:
        return lectura(EstadoReloj.CUENTA_REGRESIVA, "Cuenta regresiva para preparar entrada", segundos)
    if restante <= preparacion_segundos:
        return lectura(EstadoReloj.PREPARARSE, "Preparar duración y dirección", segundos)
    return lectura(EstadoReloj.ESPERAR, "Entrada programada más adelante", segundos)
