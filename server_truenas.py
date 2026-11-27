"""Servidor TrueNAS de TraderAssistant V5 (sin abrir ventana de escritorio).

Ejecuta una sola instancia del proceso para mantener coherentes feed, estado y
registro. El hilo de fondo continúa observando las hipótesis aun cuando no
haya navegadores conectados. NO envía órdenes ni accede a IQ Option.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from waitress import serve
from app import app
from alpaca_live import _feed as nvda_feed
from nvda_demo_v5 import _service as nvda_demo

log = logging.getLogger("traderassistant.truenas")


def observar_sin_navegador():
    """Mantener el reloj de hipótesis y guardar los resultados IEX."""
    nvda_feed.start()
    analysis = app.extensions["live_analysis"]
    while True:
        try:
            nvda_demo.tick(nvda_feed.snapshot(), analysis.snapshot())
            time.sleep(0.5)
        except Exception:
            # Solo registra tipo de excepción; nunca posibles tokens/headers.
            log.exception("Error en la observación de hipótesis; reintentando.")
            time.sleep(2.0)


def main():
    logging.basicConfig(level=logging.INFO)
    threading.Thread(
        target=observar_sin_navegador,
        name="v5-truenas-observacion",
        daemon=True,
    ).start()
    # No exponer el puerto a Internet: restringirlo con TrueNAS/red local/Tailscale.
    listen_port = int(os.environ.get("PORT", "5174"))
    log.info("Servidor V5 TrueNAS en puerto %s", listen_port)
    serve(app, host="0.0.0.0", port=listen_port, threads=12)


if __name__ == "__main__":
    main()
