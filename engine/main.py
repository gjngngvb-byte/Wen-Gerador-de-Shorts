from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
JOB_DIR = Path(os.getenv("JOB_DIR", "/tmp/wenclips"))
JOB_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
MAX_CLIPS = 5
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()
# One CPU/memory-heavy job at a time on Render's 512 MiB free instance.
worker_lock = threading.Lock()
_model = None
_model_lock = threading.Lock()

app = FastAPI(title="WenClips Engine", version="0.1.0")
configured_origins = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", "").split(",") if item.strip()]
# Keep the deployed Render frontend allowed even if the dashboard env var is stale.
required_origins = ["https://wenclips-web.onrender.com", "https://wen-gerador-de-shorts.vercel.app", "http://localhost:3000"]
origins = list(dict.fromkeys(configured_origins + required_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


class UrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


def run(command: list[str], timeout: int = 1800) -> str:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        message = (proc.stderr or proc.stdout or "Falha no processamento")[-2500:]
        raise RuntimeError(message)
    return proc.stdout.strip()


def set_job(job_id: str, **values: Any) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(values)


def get_whisper_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny"), device="cpu", compute_type="int8", cpu_threads=1, num_workers=1, download_root=os.getenv("WHISPER_MODEL_DIR", "/tmp/wenclips-model"))
        return _model


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"}
    if parsed.scheme not in {"http", "https"} or host not in allowed:
        raise HTTPException(status_code=400, detail="Use um link válido do YouTube. O vídeo precisa ser seu ou você precisa ter autorização para reutilizá-lo.")
    if host.endswith("youtube.com") and parsed.path not in {"/watch", "/shorts", "/live", "/embed"} and not parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
        raise HTTPException(status_code=400, detail="Formato de link do YouTube não reconhecido.")
    return url.strip()


def download_youtube(url: str, folder: Path) -> Path:
    validate_youtube_url(url)
    output_template = str(folder / "source.%(ext)s")
    common = [
        "yt-dlp", "--js-runtimes", "deno", "--remote-components", "ejs:github",
        "--no-playlist", "--restrict-filenames",
        # Render datacenter IPs are frequently challenged; use IPv4 and lower request rate.
        "--force-ipv4", "--sleep-requests", "1",
        "--sleep-interval", "5", "--max-sleep-interval", "10",
        # Limit source resolution as well as output resolution to reduce disk/CPU pressure.
        "--format", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4", "--max-filesize", "1G",
        "--socket-timeout", "30", "--retries", "3", "--fragment-retries", "3",
        "--extractor-retries", "3", "--retry-sleep", "linear=2:5",
        "--output", output_template,
    ]

    # Try independent yt-dlp extraction profiles automatically. A stale cookie must
    # never prevent a public video from being downloaded without authentication.
    profiles: list[tuple[str, str | None, bool]] = [
        ("padrão sem cookies", None, False),
        # Current yt-dlp guidance recommends trying mweb alongside tv/web_safari.
        # The PO-token provider only helps when extraction reaches the token stage;
        # it cannot override an IP-level login requirement.
        ("cliente mweb + tv + web_safari", "youtube:player_client=mweb,tv,web_safari", False),
        ("cliente mweb", "youtube:player_client=mweb", False),
        ("cliente tv + web_safari", "youtube:player_client=tv,web_safari", False),
        ("cliente ios", "youtube:player_client=ios", False),
        ("cliente web_safari", "youtube:player_client=web_safari", False),
        ("cliente android_vr", "youtube:player_client=android_vr", False),
    ]

    # Account cookies frequently expire and can make public-video downloads worse.
    # Ignore any configured cookie blob unless an operator explicitly opts in.
    use_account_cookies = os.getenv("YOUTUBE_USE_COOKIES", "").strip().lower() in {"1", "true", "yes"}
    cookies_b64 = os.getenv("YOUTUBE_COOKIES_BASE64", "").strip() if use_account_cookies else ""
    cookie_path = folder / "youtube-cookies.txt"
    if cookies_b64:
        try:
            cookie_bytes = base64.b64decode(cookies_b64, validate=True)
            if not cookie_bytes or b" Netscape HTTP Cookie File" not in cookie_bytes[:200]:
                raise ValueError("Formato de cookies inválido.")
            cookie_path.write_bytes(cookie_bytes)
            # Cookie-based attempt is last: stale account cookies can break otherwise
            # accessible public downloads. Cookies are never written to logs.
            profiles.append(("padrão com cookies", None, True))
        except Exception:
            cookie_path.unlink(missing_ok=True)

    failures: list[str] = []
    try:
        for label, extractor_args, use_cookies in profiles:
            # Remove partial files left by a failed attempt before trying another path.
            for partial in folder.glob("source.*"):
                if partial.is_file():
                    partial.unlink(missing_ok=True)
            command = list(common)
            if extractor_args:
                command.extend(["--extractor-args", extractor_args])
            if use_cookies:
                command.extend(["--cookies", str(cookie_path)])
            command.append(url)
            try:
                run(command, timeout=900)
                candidates = [
                    p for p in folder.glob("source.*")
                    if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
                    and p.is_file() and p.stat().st_size > 0
                ]
                if not candidates:
                    failures.append(f"{label}: o comando terminou sem gerar um arquivo.")
                    continue
                source = max(candidates, key=lambda p: p.stat().st_size)
                normalized = folder / "source.mp4"
                if source != normalized:
                    run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(normalized)], timeout=300)
                    source.unlink(missing_ok=True)
                return normalized
            except Exception as exc:
                # Keep concise diagnostics for the final user-facing job error.
                failures.append(f"{label}: {str(exc)[-450:]}")
    finally:
        cookie_path.unlink(missing_ok=True)

    # Optional external provider. Configure only an instance you own or are authorized to use.
    try:
        return download_via_cobalt(url, folder)
    except Exception as exc:
        failures.append(f"Cobalt API configurável: {str(exc)[-350:]}")
        (folder / "source.mp4").unlink(missing_ok=True)

    # Second downloader implementation: pytubefix uses its own YouTube extraction code,
    # independent from yt-dlp. It may also be blocked by YouTube, so failure is expected
    # to fall through to the next method.
    try:
        from pytubefix import YouTube

        yt = YouTube(url)
        stream = (
            yt.streams.filter(progressive=True, file_extension="mp4", resolution="720p").first()
            or yt.streams.filter(progressive=True, file_extension="mp4", resolution="480p").first()
            or yt.streams.filter(progressive=True, file_extension="mp4", resolution="360p").first()
            or yt.streams.get_highest_resolution()
        )
        if stream is None:
            raise RuntimeError("pytubefix não encontrou um formato de vídeo compatível.")
        downloaded = Path(stream.download(output_path=str(folder), filename="source.mp4"))
        if not downloaded.is_file() or downloaded.stat().st_size < 1_000_000:
            raise RuntimeError("pytubefix não gerou um arquivo de vídeo válido.")
        # Ensure a consistent filename even if the library changes the output path.
        normalized = folder / "source.mp4"
        if downloaded != normalized:
            shutil.move(str(downloaded), str(normalized))
        probe_duration(normalized)
        return normalized
    except Exception as exc:
        failures.append(f"pytubefix: {str(exc)[-350:]}")
        (folder / "source.mp4").unlink(missing_ok=True)

    # Final independent fallback: Streamlink's YouTube plugin supports live streams,
    # not ordinary YouTube VODs. Keep it bounded so a live stream cannot run forever.
    # This is a recording of an accessible live stream, not a way to bypass access controls.
    stream_path = folder / "source.ts"
    try:
        stream_path.unlink(missing_ok=True)
        run([
            "streamlink", "--stream-timeout", "30", "--stream-segment-timeout", "20",
            "--stream-segmented-duration", "00:20:00",
            "--output", str(stream_path), url, "best",
        ], timeout=1250)
        if not stream_path.is_file() or stream_path.stat().st_size < 1_000_000:
            raise RuntimeError("Streamlink não encontrou uma transmissão ao vivo acessível.")
        normalized = folder / "source.mp4"
        run(["ffmpeg", "-y", "-i", str(stream_path), "-c", "copy", "-movflags", "+faststart", str(normalized)], timeout=300)
        stream_path.unlink(missing_ok=True)
        # Reject empty/invalid captures instead of passing broken media into Whisper.
        probe_duration(normalized)
        return normalized
    except Exception as exc:
        failures.append(f"Streamlink (transmissões ao vivo): {str(exc)[-350:]}")
        stream_path.unlink(missing_ok=True)
        (folder / "source.mp4").unlink(missing_ok=True)

    details = " | ".join(failures[-5:])
    combined_errors = " ".join(failures).lower()
    youtube_requires_login = (
        "error.api.youtube.login" in combined_errors
        or "sign in to confirm you’re not a bot" in combined_errors
        or "sign in to confirm you're not a bot" in combined_errors
        or "login_required" in combined_errors
        or "this request was detected as a bot" in combined_errors
    )
    if youtube_requires_login:
        raise RuntimeError(
            "O YouTube está exigindo autenticação e bloqueou o acesso automatizado a este vídeo. "
            "O WenClips não consegue baixar esse conteúdo sem uma sessão autorizada. "
            "Envie o arquivo de vídeo ou use um link direto de mídia que você tenha autorização para acessar. "
            "Detalhes técnicos: " + details
        )
    raise RuntimeError(
        "Não foi possível obter o vídeo pelos métodos automáticos disponíveis. "
        "Envie um arquivo de vídeo que você tenha autorização para reutilizar "
        "ou use um link direto de mídia autorizado. Detalhes: " + details
    )



def download_via_cobalt(url: str, folder: Path) -> Path:
    """Use an explicitly configured Cobalt-compatible API as an optional fallback."""
    api_url = os.getenv("COBALT_API_URL", "").strip().rstrip("/")
    if not api_url:
        raise RuntimeError("COBALT_API_URL não configurado; provedor externo ignorado.")
    parsed_api = urlparse(api_url)
    if parsed_api.scheme != "https" or not parsed_api.hostname:
        raise RuntimeError("COBALT_API_URL precisa ser uma URL HTTPS válida.")

    payload = json.dumps({
        "url": url, "videoQuality": "720", "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4", "downloadMode": "auto",
        "filenameStyle": "basic", "alwaysProxy": True,
    }).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    api_key = os.getenv("COBALT_API_KEY", "").strip()
    if api_key:
        scheme = os.getenv("COBALT_AUTH_SCHEME", "Api-Key").strip() or "Api-Key"
        headers["Authorization"] = f"{scheme} {api_key}"
    request = Request(api_url + "/", data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=35) as response:
            response_data = response.read(1024 * 1024).decode("utf-8", errors="replace")
    except HTTPError as exc:
        # Preserve the provider's response body so API errors (e.g. 400) are diagnosable.
        try:
            detail = exc.read(1200).decode("utf-8", errors="replace").replace("\\n", " ")[:700]
        except Exception:
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"API externa Cobalt HTTP {exc.code}{suffix}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"API externa Cobalt indisponível: {str(exc)[:250]}") from exc

    try:
        result = json.loads(response_data)
    except json.JSONDecodeError as exc:
        raise RuntimeError("API externa retornou uma resposta que não é JSON.") from exc
    status = result.get("status")
    if status not in {"tunnel", "redirect"}:
        error = result.get("error", {})
        code = error.get("code", "resposta_sem_link") if isinstance(error, dict) else "resposta_sem_link"
        raise RuntimeError(f"API externa não forneceu vídeo: {code}")
    media_url = result.get("url")
    if not isinstance(media_url, str):
        raise RuntimeError("API externa não retornou o link do arquivo.")
    parsed_media = urlparse(media_url)
    if parsed_media.scheme != "https" or not parsed_media.hostname:
        raise RuntimeError("O provedor retornou um link de mídia HTTPS inválido.")

    target, temp = folder / "source.mp4", folder / "cobalt-download.tmp"
    max_bytes = int(os.getenv("MAX_SOURCE_MB", "1024")) * 1024 * 1024
    try:
        media_request = Request(media_url, headers={"User-Agent": "WenClips/1.0"})
        with urlopen(media_request, timeout=45) as response, temp.open("wb") as output:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                raise RuntimeError("O provedor retornou uma página de erro, não um vídeo.")
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"O vídeo excede o limite de {max_bytes // (1024 * 1024)} MB.")
                output.write(chunk)
        if temp.stat().st_size < 1_000_000:
            raise RuntimeError("O provedor retornou um arquivo vazio ou incompleto.")
        run(["ffmpeg", "-y", "-i", str(temp), "-c", "copy", "-movflags", "+faststart", str(target)], timeout=300)
        probe_duration(target)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def probe_duration(source: Path) -> float:
    raw = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)])
    duration = float(raw)
    if duration < 8:
        raise RuntimeError("O vídeo é curto demais para sugerir cortes automáticos (mínimo de 8 segundos).")
    if duration > 4 * 60 * 60:
        raise RuntimeError("O vídeo ultrapassa o limite de 4 horas.")
    return duration


def transcribe(source: Path) -> list[dict[str, Any]]:
    model = get_whisper_model()
    segments, _info = model.transcribe(str(source), language="pt", vad_filter=True, word_timestamps=False, beam_size=1)
    result = []
    for segment in segments:
        text = re.sub(r"\s+", " ", segment.text).strip()
        if text:
            result.append({"start": float(segment.start), "end": float(segment.end), "text": text})
    if not result:
        raise RuntimeError("Não encontrei fala suficiente para sugerir clipes. Tente um vídeo com áudio mais claro.")
    return result


def choose_clips(segments: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    # Rank candidate windows using conversational emphasis, useful phrases and speech density.
    full_text = " ".join(s["text"] for s in segments)
    target = min(45.0, max(20.0, duration * 0.18))
    window = min(target, max(12.0, duration - 1))
    stride = max(8.0, window * 0.45)
    keywords = re.compile(r"\b(important|importante|segredo|descobri|incrível|inacreditável|nunca|sempre|porque|por isso|como|melhor|pior|erro|dica|verdade|problema|solução|resultado|imagina|olha|então|mas|porém|wow|uau|caramba|finalmente|aprendi|aconteceu|ninguém|todo mundo|você precisa|o que)\b", re.I)
    candidates = []
    start = 0.0
    while start < duration - 6:
        end = min(duration, start + window)
        selected = [s for s in segments if s["end"] > start and s["start"] < end]
        if selected:
            words = sum(len(s["text"].split()) for s in selected)
            span = max(1.0, min(end, selected[-1]["end"]) - max(start, selected[0]["start"]))
            text = " ".join(s["text"] for s in selected)
            signals = len(keywords.findall(text))
            # Prefer windows with speech, relevant verbal signals, and a coherent start/end.
            score = (words / span) * 0.65 + signals * 1.7
            if re.search(r"[!?]", text):
                score += 0.8
            if len(text) > 120:
                score += 0.6
            candidates.append({"start": max(0.0, selected[0]["start"]), "end": min(duration, selected[-1]["end"]), "text": text, "score": score})
        start += stride
    candidates.sort(key=lambda item: item["score"], reverse=True)
    chosen = []
    for item in candidates:
        if all(item["end"] <= other["start"] or item["start"] >= other["end"] for other in chosen):
            chosen.append(item)
        if len(chosen) >= MAX_CLIPS:
            break
    if not chosen:
        chosen = [{"start": 0.0, "end": min(duration, window), "text": full_text, "score": 1.0}]
    chosen.sort(key=lambda item: item["start"])
    return chosen


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def make_ass(segments: list[dict[str, Any]], start: float, end: float, output: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,46,&H00FFFFFF,&H0000FFFF,&H00111111,&H90000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for seg in segments:
        s = max(start, seg["start"])
        e = min(end, seg["end"])
        if e <= s:
            continue
        text = seg["text"].replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        # Keep captions readable on phone screens.
        if len(text) > 52:
            words = text.split()
            lines, line = [], ""
            for word in words:
                if len(line) + len(word) + (1 if line else 0) > 34:
                    lines.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            if line:
                lines.append(line)
            text = r"\N".join(lines[:3])
        rows.append(f"Dialogue: 0,{ass_time(s-start)},{ass_time(e-start)},Default,,0,0,0,,{text}")
    output.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def render_clip(source: Path, folder: Path, index: int, clip: dict[str, Any], segments: list[dict[str, Any]]) -> Path:
    start, end = float(clip["start"]), float(clip["end"])
    duration = max(1.0, end - start)
    ass = folder / f"captions_{index}.ass"
    make_ass(segments, start, end, ass)
    output = folder / f"wenclips_{index:02d}.mp4"
    # Render 720p vertical to reduce peak memory on the free Render instance; no branding/watermark.
    escaped_ass = str(ass).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    vf = f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,subtitles='{escaped_ass}'"
    run([
        "ffmpeg", "-y", "-threads", "1", "-filter_threads", "1",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
        "-vf", vf, "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output),
    ], timeout=1800)
    return output



def upload_clip_to_storage(job_id: str, output: Path) -> str | None:
    """Upload generated clips to a private Supabase Storage bucket and return a 7-day signed URL.

    The Supabase service-role key must exist only in the backend environment, never in the browser.
    If storage is not configured, keep the current local-download behavior.
    """
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "wenclips-media").strip()
    if not base_url or not service_key:
        return None
    if not base_url.startswith("https://") or not bucket:
        raise RuntimeError("Configuração do armazenamento Supabase inválida.")

    object_path = f"{job_id}/{output.name}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "video/mp4",
        "x-upsert": "true",
    }
    upload_req = Request(
        f"{base_url}/storage/v1/object/{bucket}/{object_path}",
        data=output.read_bytes(), headers=headers, method="POST",
    )
    try:
        with urlopen(upload_req, timeout=180) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Upload Supabase retornou HTTP {response.status}.")
        sign_payload = json.dumps({"expiresIn": 604800}).encode("utf-8")
        sign_req = Request(
            f"{base_url}/storage/v1/object/sign/{bucket}/{object_path}",
            data=sign_payload,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(sign_req, timeout=30) as response:
            signed = json.loads(response.read().decode("utf-8"))
        signed_path = signed.get("signedURL") or signed.get("signedUrl")
        if not isinstance(signed_path, str) or not signed_path:
            raise RuntimeError("Supabase não retornou um link temporário para o clipe.")
        if signed_path.startswith("http://") or signed_path.startswith("https://"):
            return signed_path
        return f"{base_url}/storage/v1{signed_path if signed_path.startswith('/') else '/' + signed_path}"
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase Storage HTTP {exc.code}: {detail[:300]}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Não foi possível acessar o Supabase Storage: {str(exc)[:250]}") from exc


def process_job(job_id: str, source: Path, folder: Path) -> None:
    try:
        set_job(job_id, status="processing", progress=8, message="Analisando duração do vídeo…")
        duration = probe_duration(source)
        set_job(job_id, progress=15, message="Transcrevendo áudio em português…")
        segments = transcribe(source)
        set_job(job_id, progress=48, message="Selecionando os melhores trechos…")
        clips = choose_clips(segments, duration)
        outputs = []
        for idx, clip in enumerate(clips, start=1):
            set_job(job_id, progress=48 + int((idx - 1) / len(clips) * 45), message=f"Renderizando clipe {idx} de {len(clips)}…")
            output = render_clip(source, folder, idx, clip, segments)
            stored_url = upload_clip_to_storage(job_id, output)
            outputs.append({
                "name": output.name,
                "url": stored_url or f"/api/jobs/{job_id}/files/{output.name}",
                "start": round(clip["start"], 2),
                "end": round(clip["end"], 2),
                "duration": round(clip["end"] - clip["start"], 2),
            })
        set_job(job_id, status="completed", progress=100, message="Seus clipes estão prontos.", clips=outputs)
    except Exception as exc:
        set_job(job_id, status="failed", progress=100, message="Não foi possível processar este vídeo.", error=str(exc)[-1800:])
    finally:
        # Keep results for this running instance; hosted free filesystems may reset on restart.
        source.unlink(missing_ok=True)


def process_upload_job(job_id: str, source: Path, folder: Path) -> None:
    with worker_lock:
        process_job(job_id, source, folder)


def new_job(source: Path, folder: Path, background: BackgroundTasks) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0, "message": "Na fila de processamento…", "clips": []}
    background.add_task(process_upload_job, job_id, source, folder)
    return {"id": job_id, "status": "queued", "status_url": f"/api/jobs/{job_id}"}


@app.get("/health")
def health():
    def version_of(command: list[str]) -> str | None:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=5, check=True).stdout.strip().splitlines()[0]
        except Exception:
            return None

    return {
        "ok": True,
        "service": "WenClips Engine",
        "version": "0.1.0",
        "yt_dlp": version_of(["yt-dlp", "--version"]),
        "deno": version_of(["deno", "--version"]),
    }


def process_url_job(job_id: str, url: str, folder: Path) -> None:
    # Serialize downloads, transcription and rendering to avoid overlapping memory spikes.
    with worker_lock:
        try:
            set_job(job_id, status="downloading", progress=3, message="Obtendo o vídeo autorizado…")
            source = download_youtube(url, folder)
            process_job(job_id, source, folder)
        except Exception as exc:
            set_job(job_id, status="failed", progress=100, message="Não foi possível baixar ou processar o vídeo.", error=str(exc)[-1800:])
            shutil.rmtree(folder, ignore_errors=True)


@app.post("/api/jobs/url", status_code=202)
def create_url_job(payload: UrlRequest, background: BackgroundTasks):
    url = validate_youtube_url(payload.url)
    job_id = uuid.uuid4().hex
    folder = JOB_DIR / job_id
    folder.mkdir(parents=True, exist_ok=True)
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "status": "queued", "progress": 1, "message": "Trabalho adicionado à fila…", "clips": []}
    background.add_task(process_url_job, job_id, url, folder)
    return {"id": job_id, "status": "queued", "status_url": f"/api/jobs/{job_id}"}


@app.post("/api/jobs/upload", status_code=202)
async def create_upload_job(background: BackgroundTasks, file: UploadFile = File(...)):
    filename = Path(file.filename or "video.mp4").name
    suffix = Path(filename).suffix.lower()
    allowed = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie MP4, MOV, WEBM, MKV, M4V ou AVI.")
    job_id = uuid.uuid4().hex
    folder = JOB_DIR / job_id
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / f"source{suffix}"
    size = 0
    try:
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Arquivo acima do limite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
                out.write(chunk)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()
    if size == 0:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    return new_job(source, folder, background)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Trabalho não encontrado. O serviço pode ter reiniciado; envie o vídeo novamente.")
        return dict(job)


@app.get("/api/jobs/{job_id}/files/{filename}")
def download_clip(job_id: str, filename: str):
    if not re.fullmatch(r"wenclips_\d{2}\.mp4", filename):
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    path = JOB_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Este clipe não existe mais ou ainda não foi gerado.")
    return FileResponse(path, media_type="video/mp4", filename=filename)
