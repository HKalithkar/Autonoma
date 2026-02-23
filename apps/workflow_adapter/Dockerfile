FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements.txt

COPY libs /app/libs
COPY apps/workflow_adapter/app /app/app

EXPOSE 9004
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 9004 --workers ${WORKFLOW_ADAPTER_UVICORN_WORKERS:-4}"]
