FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first (cached layer — only rebuilds when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only source code (everything else excluded by .dockerignore)
COPY config/ ./config/
COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY streaming/ ./streaming/
COPY unsw_feature_names.json .

# Run as non-root
RUN useradd -m appuser && chown -R appuser /app
RUN apt-get update && apt-get install -y curl
USER appuser

RUN ls -R /app

CMD ["python", "src/main.py"]
