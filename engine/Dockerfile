FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates curl && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt
COPY main.py .
RUN mkdir -p /tmp/wenclips
ENV JOB_DIR=/tmp/wenclips WHISPER_MODEL=tiny
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
