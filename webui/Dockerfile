FROM python:3.13-slim

# bluez-tools provides `bluetoothctl`, used by the self-heal (trust/disconnect a
# wedged link). It talks to the HOST bluetoothd over the mounted D-Bus socket.
RUN apt-get update && apt-get install -y --no-install-recommends bluez \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

ENV XIM4_FRONTEND=/app/frontend \
    XIM4_LIBRARY=/app/data/library.json \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8477
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8477"]
