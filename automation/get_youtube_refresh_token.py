"""Run locally once to create a YouTube upload refresh token.

1. Download an OAuth Desktop client JSON from Google Cloud Console.
2. Save it beside this script as client_secret.json.
3. Run: pip install google-auth-oauthlib
4. Run: python get_youtube_refresh_token.py
5. Copy the printed refresh token into GitHub Actions secret YOUTUBE_REFRESH_TOKEN.
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_FILE = Path(__file__).with_name("client_secret.json")

if not CLIENT_FILE.exists():
    raise SystemExit("Coloque o OAuth Desktop client JSON em automation/client_secret.json (não faça commit desse arquivo).")

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")

if not credentials.refresh_token:
    raise SystemExit("O Google não retornou refresh_token. Revogue a autorização antiga e execute novamente com prompt=consent.")

print("\nYOUTUBE_REFRESH_TOKEN (guarde em segredo):\n")
print(credentials.refresh_token)
