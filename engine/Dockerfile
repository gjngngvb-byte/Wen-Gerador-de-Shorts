FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates curl unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt \
    && yt-dlp --version \
    && deno --version

# Install the same local HTTP PO-token provider used by MeTube.
# The provider and yt-dlp run in this container, so localhost is valid and
# the unauthenticated token-generation API is never exposed publicly.
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) BGUTIL_ARCH="x86_64" ;; \
      arm64) BGUTIL_ARCH="aarch64" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    BGUTIL_TAG="$(curl -fsSL -o /dev/null -w '%{url_effective}' https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest | sed 's#.*/tag/##')"; \
    test -n "$BGUTIL_TAG"; \
    curl -fL "https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/download/${BGUTIL_TAG}/bgutil-pot-linux-${BGUTIL_ARCH}" -o /usr/local/bin/bgutil-pot; \
    chmod +x /usr/local/bin/bgutil-pot; \
    PLUGIN_DIR="$(python -c 'import site; print(site.getsitepackages()[0])')"; \
    curl -fL "https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/download/${BGUTIL_TAG}/bgutil-ytdlp-pot-provider-rs.zip" -o /tmp/bgutil-provider.zip; \
    unzip -q /tmp/bgutil-provider.zip -d "$PLUGIN_DIR"; \
    rm /tmp/bgutil-provider.zip; \
    bgutil-pot --help >/dev/null

COPY main.py .
RUN mkdir -p /tmp/wenclips
ENV JOB_DIR=/tmp/wenclips WHISPER_MODEL=tiny
EXPOSE 8000
# Start the provider on loopback, then the public API. The provider's plugin
# defaults to http://127.0.0.1:4416.
CMD ["sh", "-c", "bgutil-pot server > /tmp/bgutil-pot.log 2>&1 & echo $! > /tmp/bgutil-pot.pid; exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
