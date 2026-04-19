FROM --platform=linux/amd64 python:3.12-slim

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY run.py .

# Cloud Run requires the app to listen on $PORT (default 8080)
ENV PORT=8080

RUN chown -R appuser:appuser /app
USER appuser

CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 60 run:app
