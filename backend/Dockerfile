FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app
COPY --chown=app:app backend/app /app/app
COPY --chown=app:app backend/migrations /app/migrations
COPY --chown=app:app backend/alembic.ini /app/alembic.ini
COPY --chown=app:app mcp_policy.yaml /app/mcp_policy.yaml

USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
