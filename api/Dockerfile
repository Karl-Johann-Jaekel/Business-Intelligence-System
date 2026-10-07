# Build context: repository root (needs registry/ next to api/).
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY registry/ registry/
COPY api/ api/
COPY tests/api/ tests/api/
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
