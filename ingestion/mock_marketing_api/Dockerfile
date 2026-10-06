FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.142.2 "uvicorn[standard]==0.54.0"
COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
