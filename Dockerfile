FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/app/src

WORKDIR /app

# Copy full project context
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run as non-root
RUN useradd -m appuser && chown -R appuser /app
RUN apt-get update && apt-get install -y curl
USER appuser

RUN ls -R /app

CMD ["python", "src/main.py"]
