#!/bin/sh
set -eu

export API_PORT="${PORT:-${API_PORT:-10000}}"
export API_LISTEN_ADDRESS="0.0.0.0"
export API_URL="${RENDER_EXTERNAL_URL%/}/"
export API_AUTH_REQUIRED="1"
export API_KEY_URL="file:///app/cobalt/api/keys.json"
export CORS_WILDCARD="1"
# Cobalt's session helper needs the session-generator service URL explicitly.
export YOUTUBE_SESSION_SERVER="${YOUTUBE_SESSION_SERVER:-https://wenclips-youtube-session-api.onrender.com}"

if [ -z "${COBALT_API_KEY:-}" ]; then
  echo "COBALT_API_KEY is required; configure it as a Render secret."
  exit 1
fi

node -e 'const fs=require("fs"); const k=process.env.COBALT_API_KEY; if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(k)){console.error("COBALT_API_KEY must be a UUIDv4");process.exit(1)} fs.writeFileSync("/app/cobalt/api/keys.json", JSON.stringify({[k]:{name:"wenclips-engine",limit:120}}), {mode:0o600})'

# The official session generator exposes GET /token and returns po_token /
# visitor_data. Cobalt expects POST /get_pot and potoken / visitor_data, so
# adapt the client locally and normalize the response without logging tokens.
node --input-type=module <<'NODE'
import fs from "node:fs";
const p = "/app/cobalt/api/src/processing/helpers/youtube-session.js";
let s = fs.readFileSync(p, "utf8");
const oldUrl = 'sessionServerUrl.pathname = "/get_pot";';
const oldRequest = "{ method: 'POST', dispatcher: defaultAgent }";
const normalizedRequest = `{ method: 'GET', dispatcher: defaultAgent }`;
const oldParse = "const newSession = await fetch(\n        sessionServerUrl,\n        { method: 'POST', dispatcher: defaultAgent }\n    ).then(a => a.json());";
const newParse = `const response = await fetch(sessionServerUrl, { method: 'GET', dispatcher: defaultAgent });
    if (!response.ok) {
        throw new Error(`session generator returned HTTP ${response.status}`);
    }
    const rawSession = await response.json();
    const newSession = {
        ...rawSession,
        potoken: rawSession.potoken ?? rawSession.po_token ?? rawSession.poToken,
        visitor_data: rawSession.visitor_data ?? rawSession.visitorData,
        updated: rawSession.updated ?? Date.now(),
    };`;
if (s.includes(oldUrl) && s.includes(oldParse)) {
  s = s.replace(oldUrl, 'sessionServerUrl.pathname = "/token";')
       .replace(oldParse, newParse);
  fs.writeFileSync(p, s);
  console.log("[wenclips] Adapted session endpoint and normalized token fields.");
} else if (s.includes('sessionServerUrl.pathname = "/token";') &&
           s.includes("rawSession.po_token") &&
           s.includes("session generator returned HTTP")) {
  console.log("[wenclips] Session endpoint adaptation already present.");
} else {
  console.error("[wenclips] Could not safely adapt upstream session helper; source changed.");
  process.exit(1);
}
NODE

exec pnpm start
