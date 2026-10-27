FROM node:22-bookworm-slim

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates python3 make g++     && rm -rf /var/lib/apt/lists/*     && corepack enable

WORKDIR /app
RUN git clone --depth 1 --branch main https://github.com/imputnet/cobalt.git /app/cobalt
WORKDIR /app/cobalt
RUN pnpm install --no-frozen-lockfile

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /app/cobalt/api
EXPOSE 10000
ENTRYPOINT ["/entrypoint.sh"]
