# The Natural Path Spa Management System - Backend
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend

# Set work directory
WORKDIR /app/backend

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Cloud Run injects $PORT, defaults to 8080; falls back to 8001 locally)
EXPOSE 8080

# Run the application. Shell form so ${PORT} from Cloud Run is honored.
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}
