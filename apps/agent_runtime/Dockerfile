FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements.txt

COPY libs /app/libs
COPY apps/agent_runtime/app /app/app
COPY apps/agent_runtime/prompts /app/prompts

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
