#!/bin/sh
set -eu

export API_PORT="${PORT:-${API_PORT:-10000}}"
export API_LISTEN_ADDRESS="0.0.0.0"
export API_URL="${RENDER_EXTERNAL_URL%/}/"
export API_AUTH_REQUIRED="1"
export API_KEY_URL="file:///app/cobalt/api/keys.json"
export CORS_WILDCARD="1"

if [ -z "${COBALT_API_KEY:-}" ]; then
  echo "COBALT_API_KEY is required; configure it as a Render secret."
  exit 1
fi

node -e 'const fs=require("fs"); const k=process.env.COBALT_API_KEY; if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(k)){console.error("COBALT_API_KEY must be a UUIDv4");process.exit(1)} fs.writeFileSync("/app/cobalt/api/keys.json", JSON.stringify({[k]:{name:"wenclips-engine",limit:120}}), {mode:0o600})'
exec pnpm start
