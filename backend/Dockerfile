# The Natural Path Spa Management System - Backend
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend

# Set work directory
WORKDIR /app/backend

# ffmpeg for Phase G ~60s preview clips (Celery media_preview_worker / eager local).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Prefer binary wheels (no build-essential). If a dep lacks a wheel, install
# build-essential temporarily in that layer only.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Cloud Run injects $PORT, defaults to 8080; falls back to 8001 locally)
EXPOSE 8080

# Run the application. Shell form so ${PORT} from Cloud Run is honored.
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}
