from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from faster_whisper import WhisperModel
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parent
CHANNELS_FILE = ROOT / "channels.json"
STATE_KEY = "state/shorts-queue.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
MAX_CLIP_SECONDS = 58
MIN_CLIP_SECONDS = 25
MAX_DAILY = 1


def log(message: str) -> None:
    print(f"[WenShorts] {message}", flush=True)


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=3600)
    return result.stdout.strip()


def r2():
    required = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Secrets R2 ausentes: " + ", ".join(missing))
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def load_state(client) -> dict:
    try:
        obj = client.get_object(Bucket=os.environ["R2_BUCKET"], Key=STATE_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            return {"items": [], "published": []}
        raise


def save_state(client, state: dict) -> None:
    client.put_object(
        Bucket=os.environ["R2_BUCKET"],
        Key=STATE_KEY,
        Body=json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def read_channels() -> list[str]:
    if not CHANNELS_FILE.exists():
        return []
    data = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
    return [x.strip() for x in data.get("channel_ids", []) if x.strip() and "COLOQUE" not in x]


def discover_channel_videos(channel_ids: list[str], max_items: int = 10) -> list[dict]:
    found = []
    for channel_id in channel_ids:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        request = urllib.request.Request(url, headers={"User-Agent": "WenShorts/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            xml = ET.fromstring(response.read())
        ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "atom": "http://www.w3.org/2005/Atom"}
        for entry in xml.findall("atom:entry", ns)[:max_items]:
            video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
            title = entry.findtext("atom:title", default="Vídeo do canal", namespaces=ns)
            if video_id:
                found.append({
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "source_title": title,
                    "source_url": f"https://www.youtube.com/watch?v={video_id}",
                    "discovered_at": int(time.time()),
                    "status": "waiting_for_authorized_media",
                })
    return found


def sync_feed(client, state: dict) -> None:
    channels = read_channels()
    if not channels:
        log("Nenhum channel_id configurado em automation/channels.json.")
        return
    known = {item["video_id"] for item in state.get("items", [])}
    known.update(state.get("published", []))
    added = 0
    for item in discover_channel_videos(channels):
        if item["video_id"] not in known:
            state.setdefault("items", []).append(item)
            known.add(item["video_id"])
            added += 1
    if added:
        log(f"{added} vídeo(s) novo(s) encontrado(s) nos canais monitorados.")
        save_state(client, state)


def has_authorized_source(client, video_id: str) -> bool:
    try:
        client.head_object(Bucket=os.environ["R2_BUCKET"], Key=f"authorized/{video_id}.mp4")
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def download_source(client, video_id: str, destination: Path) -> None:
    # Deliberately fetches only creator-supplied media from the private R2 bucket.
    # The YouTube URL is used for discovery/attribution, never as a media download URL.
    client.download_file(os.environ["R2_BUCKET"], f"authorized/{video_id}.mp4", str(destination))


def transcribe_and_choose(source: Path) -> tuple[float, float, list[dict]]:
    model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny"), device="cpu", compute_type="int8", cpu_threads=2)
    segments, _ = model.transcribe(str(source), language="pt", vad_filter=True, beam_size=1)
    rows = []
    for seg in segments:
        text = re.sub(r"\s+", " ", seg.text).strip()
        if text:
            rows.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    if not rows:
        raise RuntimeError("Não foi encontrada fala em português no arquivo de origem.")
    duration = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)]))
    keywords = re.compile(r"\b(important|importante|segredo|descobri|incrível|nunca|sempre|porque|como|melhor|erro|dica|verdade|problema|solução|resultado|imagina|olha|mas|porém|ninguém|você precisa)\b", re.I)
    candidates = []
    span = min(MAX_CLIP_SECONDS, max(MIN_CLIP_SECONDS, duration * 0.18))
    stride = max(8.0, span * 0.35)
    start = 0.0
    while start < duration - MIN_CLIP_SECONDS:
        end = min(duration, start + span)
        chosen = [s for s in rows if s["end"] > start and s["start"] < end]
        if chosen:
            spoken = sum(len(s["text"].split()) for s in chosen)
            text = " ".join(s["text"] for s in chosen)
            score = spoken / max(1.0, end - start) + 2.0 * len(keywords.findall(text))
            candidates.append((score, max(0.0, chosen[0]["start"]), min(duration, chosen[-1]["end"])))
        start += stride
    if not candidates:
        raise RuntimeError("Não foi possível selecionar um trecho falado.")
    _, clip_start, clip_end = max(candidates, key=lambda x: x[0])
    if clip_end - clip_start < MIN_CLIP_SECONDS:
        clip_end = min(duration, clip_start + MIN_CLIP_SECONDS)
    return clip_start, min(clip_end, clip_start + MAX_CLIP_SECONDS), rows


def ass_time(seconds: float) -> str:
    cs = max(0, int(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def create_subtitles(rows: list[dict], start: float, end: float, path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,46,&H00FFFFFF,&H0000FFFF,&H00111111,&H90000000,1,0,0,0,100,100,0,0,1,3,1,2,50,50,140,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for row in rows:
        a, b = max(start, row["start"]), min(end, row["end"])
        if b <= a:
            continue
        caption = row["text"].replace("{", r"\{").replace("}", r"\}")
        lines.append(f"Dialogue: 0,{ass_time(a-start)},{ass_time(b-start)},Default,,0,0,0,,{caption}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def render_short(source: Path, output: Path, start: float, end: float, rows: list[dict]) -> None:
    ass = output.with_suffix(".ass")
    create_subtitles(rows, start, end, ass)
    escaped = str(ass).replace("\\", "\\\\").replace(":", "\\:")
    vf = f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,subtitles='{escaped}'"
    run([
        "ffmpeg", "-y", "-threads", "2", "-filter_threads", "1",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{end-start:.3f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ])


def youtube_client():
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Secrets OAuth do YouTube ausentes: " + ", ".join(missing))
    credentials = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def make_title(transcript: list[dict], source_title: str) -> str:
    words = " ".join(row["text"] for row in transcript).strip()
    sentence = re.split(r"(?<=[.!?])\s+", words)[0] if words else source_title
    title = re.sub(r"\s+", " ", sentence).strip(" .!?")[:82]
    if len(title) < 12:
        title = source_title[:82]
    return f"{title} #Shorts"[:100]


def publish(video: Path, title: str, source_url: str) -> str:
    youtube = youtube_client()
    body = {
        "snippet": {
            "title": title,
            "description": f"Trecho editado com autorização do titular do conteúdo.\nVídeo original: {source_url}\n\n#Shorts #YouTubeShorts",
            "tags": ["Shorts", "YouTubeShorts"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        },
        "status": {
            "privacyStatus": os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Upload: {int(status.progress() * 100)}%")
    return response["id"]


def process_one(client, state: dict) -> bool:
    items = state.setdefault("items", [])
    for item in items:
        if item.get("status") != "waiting_for_authorized_media":
            continue
        video_id = item["video_id"]
        if not has_authorized_source(client, video_id):
            continue
        with tempfile.TemporaryDirectory(prefix="wenshorts-") as tmp:
            folder = Path(tmp)
            source = folder / "source.mp4"
            output = folder / "short.mp4"
            log(f"Processando mídia autorizada para {video_id}.")
            download_source(client, video_id, source)
            start, end, transcript = transcribe_and_choose(source)
            render_short(source, output, start, end, transcript)
            title = make_title(transcript, item.get("source_title", "Short"))
            published_id = publish(output, title, item["source_url"])
        item["status"] = "published"
        item["youtube_video_id"] = published_id
        item["published_at"] = int(time.time())
        state.setdefault("published", []).append(video_id)
        save_state(client, state)
        log(f"Publicado: https://www.youtube.com/shorts/{published_id}")
        return True
    return False


def main() -> None:
    client = r2()
    state = load_state(client)
    sync_feed(client, state)
    published = 0
    for _ in range(MAX_DAILY):
        if not process_one(client, state):
            break
        published += 1
    log(f"Execução concluída. Shorts publicados nesta execução: {published}.")


if __name__ == "__main__":
    main()
