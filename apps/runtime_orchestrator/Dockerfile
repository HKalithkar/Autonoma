FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements.txt

COPY libs /app/libs
COPY apps/runtime_orchestrator/app /app/app
COPY apps/api/app /app/apps/api/app

ENV PYTHONPATH=/app

EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
