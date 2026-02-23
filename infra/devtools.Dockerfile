FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt requirements.txt
COPY requirements-dev.txt requirements-dev.txt

RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements-dev.txt
