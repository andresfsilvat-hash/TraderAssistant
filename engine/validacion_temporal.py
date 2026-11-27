"""Evaluación fuera de muestra de hipótesis a vencimiento fijo.

No genera señales ni órdenes. Requiere precios de entrada y salida observados
en instantes de ejecución comparables; no aproxima 30 s usando velas 1 min.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt

from engine.reloj_entrada import HORIZONTES_SEGUNDOS


@dataclass(frozen=True)
class Observacion:
    detectada_utc: datetime
    entrada_utc: datetime
    vencimiento_utc: datetime
    duracion_segundos: int
    direccion: str
    precio_entrada: float
    precio_salida: float
    fuente: str
    payout_neto: float | None = None
    tolerancia_vencimiento_segundos: float = 0.5

    def __post_init__(self) -> None:
        instantes = (self.detectada_utc, self.entrada_utc, self.vencimiento_utc)
        if any(not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None
               for t in instantes):
            raise ValueError("Cada evento requiere timestamps con zona horaria")
        if self.duracion_segundos not in HORIZONTES_SEGUNDOS:
            raise ValueError("Horizonte no permitido")
        if self.direccion not in ("SUBE", "BAJA"):
            raise ValueError("Dirección no permitida")
        if not self.detectada_utc <= self.entrada_utc:
            raise ValueError("La señal debe conocerse antes de la entrada")
        delta = (self.vencimiento_utc - self.entrada_utc).total_seconds()
        if not isfinite(self.tolerancia_vencimiento_segundos) or self.tolerancia_vencimiento_segundos < 0:
            raise ValueError("Tolerancia inválida")
        if abs(delta - self.duracion_segundos) > self.tolerancia_vencimiento_segundos:
            raise ValueError("No se observó el vencimiento seleccionado")
        if (not isfinite(self.precio_entrada) or not isfinite(self.precio_salida)
                or min(self.precio_entrada, self.precio_salida) <= 0):
            raise ValueError("Precios inválidos")
        if not self.fuente.strip():
            raise ValueError("Fuente ausente")
        if self.payout_neto is not None and (not isfinite(self.payout_neto) or not 0 <= self.payout_neto <= 1):
            raise ValueError("Payout neto debe estar entre 0 y 1")


def _resultado(item: Observacion) -> str:
    diferencia = item.precio_salida - item.precio_entrada
    if diferencia == 0:
        return "EMPATE"
    correcto = (diferencia > 0) if item.direccion == "SUBE" else (diferencia < 0)
    return "ACIERTO" if correcto else "FALLO"


def _wilson_inferior(aciertos: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = aciertos / total
    z2 = z * z
    return max(0.0, (p + z2 / (2 * total) -
                    z * sqrt(p * (1 - p) / total + z2 / (4 * total * total))) /
                   (1 + z2 / total))


def resumen_fuera_muestra(
    observaciones: list[Observacion],
    *,
    corte_utc: datetime,
    minimo_prueba: int = 30,
    incluir_fuentes: tuple[str, ...] | None = None,
) -> dict:
    """Calcula métricas temporales sin entrenar y probar sobre el mismo evento.

    Las observaciones anteriores al corte son entrenamiento; las posteriores,
    prueba. El resumen no autoriza operar; la cobertura y latencia del broker
    deben verificarse por separado.
    """
    if corte_utc.tzinfo is None or corte_utc.utcoffset() is None:
        raise ValueError("El corte requiere zona horaria")
    if minimo_prueba < 1:
        raise ValueError("minimo_prueba debe ser >= 1")
    cutoff = corte_utc.astimezone(timezone.utc)
    filtradas = [x for x in observaciones if incluir_fuentes is None or x.fuente in incluir_fuentes]
    # Rechazar duplicados para impedir inflar la precisión con repeticiones.
    claves = [(x.fuente, x.entrada_utc.astimezone(timezone.utc), x.duracion_segundos,
               x.direccion) for x in filtradas]
    if len(claves) != len(set(claves)):
        raise ValueError("Observaciones duplicadas")
    resultado = {}
    for h in sorted(HORIZONTES_SEGUNDOS):
        rows = [x for x in filtradas if x.duracion_segundos == h]
        # Ningún evento que termine después del corte entra en entrenamiento.
        train = [x for x in rows if x.vencimiento_utc.astimezone(timezone.utc) < cutoff]
        test = [x for x in rows if x.detectada_utc.astimezone(timezone.utc) >= cutoff]
        omitted = len(rows) - len(train) - len(test)
        a = sum(_resultado(x) == "ACIERTO" for x in test)
        f = sum(_resultado(x) == "FALLO" for x in test)
        e = len(test) - a - f
        evaluables = a + f
        payouts = [x.payout_neto for x in test if _resultado(x) != "EMPATE"]
        payouts_completos = bool(payouts) and all(p is not None for p in payouts)
        utilidad = (sum((x.payout_neto if _resultado(x) == "ACIERTO" else -1.0)
                         for x in test if _resultado(x) != "EMPATE")
                    if payouts_completos else None)
        resultado[str(h)] = {
            "entrenamiento": len(train),
            "prueba": len(test),
            "excluidos_frontera": omitted,
            "aciertos": a, "fallos": f, "empates": e,
            "tasa_acierto": a / evaluables if evaluables else None,
            "limite_inferior_wilson_95": _wilson_inferior(a, evaluables),
            "utilidad_neta_unidades": utilidad,
            "evidencia_suficiente": evaluables >= minimo_prueba,
            "estado": "EVALUACION_EXPERIMENTAL_NO_VALIDADA",
        }
    return {"corte_utc": cutoff.isoformat(), "minimo_prueba": minimo_prueba,
            "fuentes": sorted({x.fuente for x in filtradas}),
            "horizontes": resultado, "operativa_autorizada": False}
