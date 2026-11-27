"""V5 NVIDIA: demo prospectiva con alerta +10s y resultado IEX observable.

Solo lectura, ninguna orden de mercado. Usa las cotizaciones punto medio bid/ask
de Alpaca IEX como proxy de comprobación. NO equivale a una cotización, ejecución
ni vencimiento de IQ Option/NVIDIA Blitz. La puntuación 0..100 indica fuerza de
concordancia técnica, NUNCA probabilidad calibrada de ganancia.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import threading
import uuid

from flask import jsonify, request

# Fuera del repositorio: git stash/pull nunca borra el histórico de hipótesis.
DATA_FILE = Path.home() / "Documents" / "TraderAssistant" / "registro_nvda_v5.json"
# 600s se conserva para estadísticas históricas, pero no aparece en la imagen IQ Option.
DURATIONS = (30, 45, 60, 120, 180, 300, 600)
VENCIMIENTOS_SELECCIONABLES = (30, 45, 60, 120, 180, 300)
ENTRY_DELAY_SECONDS = 10
OBSERVATION_GRACE_SECONDS = 6
# Pequeña pausa de revisión tras el vencimiento, antes de otra alerta.
REVIEW_DELAY_SECONDS = 5
CANDLE_MAX_AGE_SECONDS = 150
QUOTE_MAX_AGE_SECONDS = 4
ALGORITHM = "demo-confluencia-nvda-v5-2-manual-expiry"


def _parse(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    return t.astimezone(timezone.utc) if t.tzinfo is not None and t.utcoffset() is not None else None


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def _ts(now):
    return now.astimezone(timezone.utc).isoformat()


def _signed(value, threshold=0):
    return 1 if value > threshold else -1 if value < -threshold else 0


def _quote(snapshot, now, *, at=None):
    """Captura un precio proxy SOLO a partir de una cotización realmente recibida.

    Nunca usa el último cierre histórico para fingir un precio de ejecución.
    Requiere timestamp de proveedor y recepción reciente, ambos posteriores al
    instante objetivo; compara punto medio con punto medio.
    """
    obj = snapshot.get("last_quote") or {}
    bid, ask = _num(obj.get("bid")), _num(obj.get("ask"))
    t = _parse(obj.get("timestamp"))
    rx = _parse(snapshot.get("last_quote_received_at"))
    if (bid is None or ask is None or bid <= 0 or ask < bid or
            t is None or rx is None or abs((now-rx).total_seconds()) > QUOTE_MAX_AGE_SECONDS or
            (now-t).total_seconds() > QUOTE_MAX_AGE_SECONDS or
            (t-now).total_seconds() > 1.0):
        return None
    if at is not None and (t-at).total_seconds() < 0:
        return None
    if at is not None and (t-at).total_seconds() > OBSERVATION_GRACE_SECONDS:
        return None
    return {"price": round((bid+ask)/2, 6), "timestamp": _ts(t),
            "source": "IEX_MID_BID_ASK_PROXY", "bid": bid, "ask": ask}


def _last_complete(snapshot, now):
    bars = snapshot.get("candles") or []
    for b in reversed(bars):
        if not isinstance(b, dict) or b.get("provisional") is not False:
            continue
        start = _num(b.get("time"))
        close = _num(b.get("close"))
        opened = _num(b.get("open"))
        if start is None or close is None or opened is None or close <= 0 or opened <= 0:
            continue
        age = now.timestamp() - (start + 60)
        if 0 <= age <= CANDLE_MAX_AGE_SECONDS:
            return b
    return None


def proponer_hipotesis(market, analysis, *, ahora_utc):
    """Una hipótesis por vela oficial nueva, no promesa de rentabilidad."""
    now = ahora_utc.astimezone(timezone.utc)
    fail = lambda reason: {"disponible": False, "motivo": reason}
    if market.get("symbol") != "NVDA" or analysis.get("symbol") != "NVDA":
        return fail("Disponible únicamente para NVIDIA (NVDA).")
    clock = market.get("market_clock") or {}
    verified = _parse(clock.get("checked_at"))
    if (clock.get("source") != "alpaca" or clock.get("is_open") is not True or
            verified is None or not -1 <= (now-verified).total_seconds() <= 600):
        return fail("Bolsa cerrada o horario Alpaca sin verificar.")
    if market.get("status") != "conectado":
        return fail("Alpaca IEX no está suscrito.")
    if analysis.get("status") != "ready" or analysis.get("stale") is not False:
        return fail("Cálculo técnico todavía no está listo o está obsoleto.")
    bar = _last_complete(market, now)
    if bar is None:
        return fail("No existe una vela 1m oficial cerrada reciente.")
    candle_time = _parse(analysis.get("last_candle_time"))
    if candle_time is None or int(candle_time.timestamp()) != int(bar["time"]):
        return fail("El análisis todavía no corresponde a la última vela oficial.")
    # Requerir un proxy contemporáneo ANTES de anunciar 10 s.
    if _quote(market, now) is None:
        return fail("Sin cotización IEX reciente para observar la entrada.")
    values = analysis.get("values") or {}
    close = _num(values.get("close"))
    sma20 = _num(values.get("sma20_1m"))
    hist = _num(values.get("macd_histogram"))
    ret = _num(values.get("return_3m_percent"))
    rsi = _num(values.get("rsi_14"))
    if None in (close, sma20, hist, ret, rsi):
        return fail("Faltan indicadores mínimos (SMA20, MACD, retorno 3m, RSI).")

    evidence = []
    def vote(label, side, weight, detail):
        if side:
            evidence.append({"indicador": label, "voto": "SUBE" if side > 0 else "BAJA",
                             "peso": weight, "detalle": detail})
    vote("MACD histograma", _signed(hist), 3, f"Histograma {hist:+.5f}")
    vote("Precio / SMA20", _signed(close-sma20), 2, f"Cierre {close:.3f}, SMA20 {sma20:.3f}")
    vote("Retorno 3min", _signed(ret), 2, f"Retorno 3m {ret:+.3f}%")
    vote("RSI14", _signed(rsi-50, 2), 1, f"RSI {rsi:.1f}")
    open_price = _num(bar.get("open"))
    vote("Última vela cerrada", _signed(close-open_price), 1,
         f"Apertura {open_price:.3f}, cierre {close:.3f}")
    # Contexto de 1h pesa solo como evidencia secundaria, si el proveedor lo permite.
    hour = (analysis.get("context") or {}).get("1h") or {}
    if hour.get("status") in ("ready", "sufficient"):
        vote("Contexto 1h", {"Alcista": 1, "Bajista": -1}.get(hour.get("trend"), 0), 1,
             f"Tendencia 1h {hour.get('trend')}")
    total = sum(e["peso"] for e in evidence)
    net = sum(e["peso"] * (1 if e["voto"] == "SUBE" else -1) for e in evidence)
    if not net:
        # Desempate puramente mecánico y público para no bloquear la prueba.
        net = _signed(close-open_price) or _signed(hist) or 1
    direction = "SUBE" if net > 0 else "BAJA"
    in_favor = sum(e["peso"] for e in evidence if e["voto"] == direction)
    contra = total - in_favor
    strength = round(100 * in_favor / total) if total else 0

    # El motor decide SOLO la dirección. El vencimiento lo asigna el
    # usuario antes de la entrada, copiándolo de la configuración persistida.
    return {"disponible": True, "motivo": "Hipótesis mecánica para medir, no validada.",
            "direccion": direction, "duracion_segundos": None,
            "puntaje_concordancia": strength, "peso_favor": in_favor,
            "peso_contra": contra, "evidencias": evidence,
            "vela_id": int(bar["time"]), "version": ALGORITHM,
            "nota": "Puntaje técnico, NO probabilidad de acierto."}


class NVDADemoService:
    def __init__(self, *, path=DATA_FILE, when=None):
        self.path = Path(path)
        self.when = when or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.entries = []
        self.current = None
        self.last_candle_id = None
        # Sin vencimiento inicial: el usuario debe seleccionarlo explícitamente.
        self.vencimiento_seleccionado_segundos = None
        self._load()

    def _load(self):
        try:
            if not self.path.is_file():
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema") != 1 or not isinstance(raw.get("entries"), list):
                return
            self.entries = [x for x in raw["entries"] if isinstance(x, dict)][-1000:]
            selected = raw.get("vencimiento_seleccionado_segundos")
            if type(selected) is int and selected in VENCIMIENTOS_SELECCIONABLES:
                self.vencimiento_seleccionado_segundos = selected
            # No fabricar entradas/resultados que habrían ocurrido mientras el PC estaba apagado.
            for x in self.entries:
                if x.get("resultado") == "PENDIENTE":
                    x["resultado"] = "NO_EVALUABLE"
                    x["motivo_resultado"] = "Aplicación reiniciada; seguimiento interrumpido."
            if self.entries:
                self.last_candle_id = self.entries[-1].get("vela_id")
        except (OSError, ValueError, TypeError):
            pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {"schema": 1, "entries": self.entries[-1000:],
                 "vencimiento_seleccionado_segundos": self.vencimiento_seleccionado_segundos}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def configurar_vencimiento(self, segundos):
        # Rechazar floats, strings y bool: solo los valores del selector IQ.
        if type(segundos) is not int or segundos not in VENCIMIENTOS_SELECCIONABLES:
            raise ValueError("Selecciona 30 s, 45 s, 1 min, 2 min, 3 min o 5 min.")
        with self.lock:
            self.vencimiento_seleccionado_segundos = segundos
            self._save()
            return {
                "vencimiento_seleccionado_segundos": segundos,
                "opciones_vencimiento_segundos": list(VENCIMIENTOS_SELECCIONABLES),
                "aplica_desde": "SIGUIENTE_HIPOTESIS",
                "aviso": "No cambia el vencimiento de una hipótesis en curso.",
            }

    def _bloqueo_vencimiento(self, now):
        """No solapar hipótesis, incluso tras falta de tick o reinicio.

        El vencimiento original es la referencia inmutable. Un resultado
        NO_EVALUABLE no equivale al fin del vencimiento elegido en IQ Option.
        """
        if not self.entries:
            return None
        last = self.entries[-1]
        expiry = _parse(last.get("vencimiento_utc"))
        if expiry is None:
            return None
        release = expiry + timedelta(seconds=REVIEW_DELAY_SECONDS)
        if now >= release:
            return None
        remaining_expiry = max(0, math.ceil((expiry-now).total_seconds()))
        return {
            "hasta_utc": _ts(expiry),
            "liberar_nueva_senal_utc": _ts(release),
            "segundos_hasta_vencimiento": remaining_expiry,
            "segundos_hasta_nueva_senal": max(1, math.ceil((release-now).total_seconds())),
            "fase": "ESPERANDO_VENCIMIENTO" if now < expiry else "REVISION",
            "direccion": last.get("direccion"),
            "duracion_segundos": last.get("duracion_segundos"),
            "resultado": last.get("resultado"),
            "motivo": "No se emite otra cuenta regresiva antes del vencimiento anterior, "
                      "aunque falte la cotización y se marque NO_EVALUABLE.",
        }

    def _create(self, candidate, now):
        target = now + timedelta(seconds=ENTRY_DELAY_SECONDS)
        # La cuenta para entrar termina EN target. El vencimiento arranca
        # EN target, no cuando se empieza a contar 10, 9, 8...
        expiry = target + timedelta(seconds=candidate["duracion_segundos"])
        x = {
            "id": str(uuid.uuid4()), "simbolo": "NVDA", "version": ALGORITHM,
            "vela_id": candidate["vela_id"],
            "creada_utc": _ts(now), "entrada_programada_utc": _ts(target),
            "inicio_vencimiento_utc": _ts(target),
            "vencimiento_utc": _ts(expiry),
            "espera_entrada_segundos": ENTRY_DELAY_SECONDS,
            "tiempo_vencimiento_segundos": candidate["duracion_segundos"],
            "direccion": candidate["direccion"],
            "duracion_segundos": candidate["duracion_segundos"],
            "origen_vencimiento": "SELECCION_MANUAL_USUARIO",
            "puntaje_concordancia": candidate["puntaje_concordancia"],
            "evidencias": deepcopy(candidate["evidencias"]),
            "peso_favor": candidate["peso_favor"], "peso_contra": candidate["peso_contra"],
            "precio_entrada": None, "precio_salida": None,
            "fuente_entrada": None, "fuente_salida": None,
            "resultado": "PENDIENTE", "motivo_resultado": None}
        self.entries.append(x)
        self.entries = self.entries[-1000:]
        self.current = x
        self.last_candle_id = candidate["vela_id"]
        self._save()

    def _finish(self, outcome, reason=None):
        self.current["resultado"] = outcome
        self.current["motivo_resultado"] = reason
        self.current = None
        self._save()

    def _advance(self, market, now):
        x = self.current
        if x is None:
            return
        if market.get("symbol") != "NVDA":
            self._finish("NO_EVALUABLE", "Se cambió de activo durante la observación.")
            return
        start = _parse(x["entrada_programada_utc"])
        expiry = _parse(x["vencimiento_utc"])
        if now < start:
            if market.get("symbol") != "NVDA" or market.get("status") != "conectado":
                self._finish("NO_EVALUABLE", "Conexión o símbolo cambiados antes de la entrada.")
            return
        if x["precio_entrada"] is None:
            q = _quote(market, now, at=start)
            if q:
                x["precio_entrada"] = q["price"]
                x["fuente_entrada"] = q["source"]
                x["bid_entrada"] = q["bid"]
                x["ask_entrada"] = q["ask"]
                x["observada_entrada_utc"] = q["timestamp"]
                self._save()
            elif (now-start).total_seconds() > OBSERVATION_GRACE_SECONDS:
                self._finish("NO_EVALUABLE", "No se observó cotización IEX puntual en la entrada.")
            return
        if now < expiry:
            return
        q = _quote(market, now, at=expiry)
        if not q:
            if (now-expiry).total_seconds() > OBSERVATION_GRACE_SECONDS:
                self._finish("NO_EVALUABLE", "No se observó cotización IEX puntual al vencimiento.")
            return
        x["precio_salida"] = q["price"]
        x["fuente_salida"] = q["source"]
        x["bid_salida"] = q["bid"]
        x["ask_salida"] = q["ask"]
        x["observada_salida_utc"] = q["timestamp"]
        delta = x["precio_salida"] - x["precio_entrada"]
        if delta == 0:
            outcome = "EMPATE"
        elif (delta > 0) == (x["direccion"] == "SUBE"):
            outcome = "ACIERTO"
        else:
            outcome = "FALLO"
        self._finish(outcome, "Resultado IEX MID bid/ask proxy; NO es operación IQ Option.")

    def _stats(self):
        completed = [x for x in self.entries if x.get("resultado") in
                     ("ACIERTO", "FALLO", "EMPATE")]
        wins = sum(x["resultado"] == "ACIERTO" for x in completed)
        losses = sum(x["resultado"] == "FALLO" for x in completed)
        ties = sum(x["resultado"] == "EMPATE" for x in completed)
        denominator = wins + losses
        return {"total_hipotesis": len(self.entries),
                "evaluadas": len(completed), "aciertos": wins,
                "fallos": losses, "empates": ties,
                "no_evaluables": sum(x.get("resultado") == "NO_EVALUABLE" for x in self.entries),
                "tasa_acierto_pct": round(100 * wins/denominator, 2) if denominator else None,
                "base_porcentaje": "Aciertos/(aciertos+fallos); empates no cuentan",
                "indicador": "Muestra local IEX proxy, no resultados de IQ Option",
                "version": ALGORITHM}

    def _stats_by_duration(self):
        out = {}
        for duration in DURATIONS:
            entries = [x for x in self.entries
                       if x.get("duracion_segundos") == duration]
            wins = sum(x.get("resultado") == "ACIERTO" for x in entries)
            losses = sum(x.get("resultado") == "FALLO" for x in entries)
            ties = sum(x.get("resultado") == "EMPATE" for x in entries)
            n = wins + losses
            out[str(duration)] = {
                "hipotesis": len(entries), "aciertos": wins, "fallos": losses,
                "empates": ties, "no_evaluables":
                    sum(x.get("resultado") == "NO_EVALUABLE" for x in entries),
                "tasa_acierto_pct": round(100 * wins/n, 2) if n else None}
        return out

    def tick(self, market, analysis, *, now=None):
        now = now or self.when()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("La hora actual debe tener zona horaria")
        with self.lock:
            market, analysis = market or {}, analysis or {}
            self._advance(market, now)
            bloqueo = self._bloqueo_vencimiento(now)
            # Una vela nueva puede dar otra dirección/duración, pero no abre
            # segunda alerta mientras el vencimiento anterior siga vigente.
            candidate = proponer_hipotesis(market, analysis, ahora_utc=now)
            selected = self.vencimiento_seleccionado_segundos
            if selected is None and candidate.get("disponible"):
                candidate = dict(candidate, disponible=False,
                                 motivo="Selecciona primero el vencimiento en el panel NVIDIA.",
                                 duracion_segundos=None)
            if (self.current is None and bloqueo is None and selected is not None and
                    candidate.get("disponible") and
                    candidate["vela_id"] != self.last_candle_id):
                fixed_candidate = dict(candidate, duracion_segundos=selected)
                self._create(fixed_candidate, now)
            bloqueo = self._bloqueo_vencimiento(now)
            x = self.current
            state = "ESPERAR"
            remaining = None
            if x is None and bloqueo is not None:
                state = ("ESPERANDO_VENCIMIENTO" if bloqueo["fase"] == "ESPERANDO_VENCIMIENTO"
                         else "REVISION_RESULTADO")
            if x is not None:
                start = _parse(x["entrada_programada_utc"])
                expiry = _parse(x["vencimiento_utc"])
                if now < start:
                    state = "CUENTA_REGRESIVA"
                    remaining = max(1, math.ceil((start-now).total_seconds()))
                elif x["precio_entrada"] is None:
                    state = "ENTRADA_PROGRAMADA"
                    remaining = 0
                elif now < expiry:
                    state = "EN_SEGUIMIENTO"
                else:
                    state = "EVALUANDO"
            result = {"estado": state, "segundos_para_entrada": remaining,
                      "bloqueo_vencimiento": deepcopy(bloqueo),
                      "vencimiento_seleccionado_segundos": selected,
                      "opciones_vencimiento_segundos": list(VENCIMIENTOS_SELECCIONABLES),
                      "modo_vencimiento": "SELECCION_MANUAL_USUARIO",
                      "hipotesis_activa": deepcopy(x), "ultima_hipotesis":
                      deepcopy(self.entries[-1]) if self.entries else None,
                      "candidato_actual": candidate, "estadisticas": self._stats(),
                      "estadisticas_por_duracion": self._stats_by_duration(),
                      "operativa_autorizada": False, "modo": "SIMULACION_IEX",
                      "aviso": "SOLO PRUEBA; NO es precio/vencimiento IQ Option. "
                               "Puntuación 0–100 de confluencia NO es probabilidad.",
                      "reloj_servidor_utc": _ts(now),
                      "descripcion_temporal": "La cuenta previa (10 segundos) termina "
                          "al llegar a la entrada simulada. El vencimiento empieza "
                          "en esa entrada y dura los segundos indicados; en IQ Option "
                          "el vencimiento real depende del clic y reglas de la plataforma."}
            return result


_service = NVDADemoService()


def register_nvda_demo_v5(app, *, service=None, feed=None, analysis_service=None):
    from alpaca_live import _feed as default_feed
    service = service or _service
    feed = feed or default_feed

    @app.route("/api/v5/demo", methods=["GET"])
    def nvda_demo_state():
        actual_analysis = analysis_service or app.extensions["live_analysis"]
        result = service.tick(feed.snapshot(), actual_analysis.snapshot())
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/v5/demo/vencimiento", methods=["POST"])
    def nvda_demo_set_expiry():
        payload = request.get_json(silent=True)
        requested = payload.get("vencimiento_segundos") if isinstance(payload, dict) else None
        try:
            config = service.configurar_vencimiento(requested)
        except ValueError:
            return jsonify({"error": "Vencimiento inválido. Selecciona 30, 45, 60, 120, 180 o 300 segundos."}), 400
        response = jsonify({"status": "ok", **config})
        response.headers["Cache-Control"] = "no-store"
        return response
