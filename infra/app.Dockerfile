# Pipeline image: ingestion, dbt, Dagster webserver/daemon and the `bis` CLI.
# Build context: repository root.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DAGSTER_HOME=/app/orchestration/dagster_home

WORKDIR /app
COPY . .
# Editable install: the code resolves dbt/, registry/ and data/ relative to the source tree.
RUN pip install -e . \
    # dbt parse never connects; it needs the variable only to render the profile.
    && BIS_PG_PASSWORD=build-only dbt parse --project-dir dbt --profiles-dir dbt \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown -R app /app/data /app/orchestration/dagster_home /app/dbt
USER app
