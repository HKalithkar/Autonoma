FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements.txt

COPY libs /app/libs
COPY apps/plugin_gateway/app /app/app

EXPOSE 8002
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers ${PLUGIN_GATEWAY_UVICORN_WORKERS:-4}"]
