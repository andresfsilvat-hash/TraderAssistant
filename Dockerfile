# Imagen de servidor: SIN pywebview ni dependencias de Windows.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/trader
WORKDIR /app

COPY requirements-server.txt /app/requirements-server.txt
RUN python -m pip install --no-cache-dir -r /app/requirements-server.txt

COPY . /app/
# La lista local es privada en Windows, así que creamos una por defecto.
RUN printf '%s\n' '{"tickers":["NVDA"]}' > /app/config.json \
    && groupadd --gid 3001 trader \
    && useradd --uid 1000 --gid 3001 --create-home trader \
    && mkdir -p /app/cache /home/trader/Documents/TraderAssistant \
    && chown -R trader:trader /app /home/trader

USER trader
EXPOSE 5174
CMD ["python", "-u", "server_truenas.py"]
