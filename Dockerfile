FROM python:3.12-slim

# Security: Non-root user
RUN useradd -m -u 1001 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Mount /app/data read-only at runtime
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8060

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/health')"

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8060", "--workers", "2", "--threads", "4", "--timeout", "60"]
