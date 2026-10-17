
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies separately for better build caching.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .



CMD ["python", "-u", "main.py"]
