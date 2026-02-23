FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir uv \
    && uv pip install --system -r requirements.txt

COPY libs /app/libs
COPY apps/api/app /app/app
COPY apps/api/alembic /app/alembic
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/entrypoint.sh /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
