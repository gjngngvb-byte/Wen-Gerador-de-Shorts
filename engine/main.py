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
_model = None
_model_lock = threading.Lock()

app = FastAPI(title="WenClips Engine", version="0.1.0")
origins = [item.strip() for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if item.strip()]
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
            _model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny"), device="cpu", compute_type="int8")
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
    command = [
        "yt-dlp", "--js-runtimes", "deno", "--remote-components", "ejs:github",
        "--no-playlist", "--restrict-filenames",
        "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4", "--max-filesize", "1G",
        "--output", output_template,
    ]
    # Optional authenticated session cookie file supplied through Render secret env var.
    # Never commit cookie files or print their contents to logs.
    cookies_b64 = os.getenv("YOUTUBE_COOKIES_BASE64", "").strip()
    if cookies_b64:
        cookie_path = JOB_DIR / "youtube-cookies.txt"
        try:
            cookie_bytes = base64.b64decode(cookies_b64, validate=True)
            if not cookie_bytes or b" Netscape HTTP Cookie File" not in cookie_bytes[:200]:
                raise ValueError("Formato de cookies inválido; exporte no formato Netscape.")
            cookie_path.write_bytes(cookie_bytes)
        except Exception as exc:
            raise RuntimeError("YOUTUBE_COOKIES_BASE64 está inválido. Configure uma exportação Netscape válida no segredo do servidor.") from exc
        command.extend(["--cookies", str(cookie_path)])
    command.append(url)
    try:
        run(command, timeout=1200)
    finally:
        if cookies_b64:
            cookie_path.unlink(missing_ok=True)
    candidates = [p for p in folder.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
    if not candidates:
        raise RuntimeError("Não foi possível obter o vídeo. Confira se o link está acessível e se você tem autorização para baixá-lo.")
    source = max(candidates, key=lambda p: p.stat().st_size)
    normalized = folder / "source.mp4"
    if source != normalized:
        run(["ffmpeg", "-y", "-i", str(source), "-c", "copy", str(normalized)], timeout=600)
        source.unlink(missing_ok=True)
    return normalized


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
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,64,&H00FFFFFF,&H0000FFFF,&H00111111,&H90000000,1,0,0,0,100,100,0,0,1,4,1,2,90,90,210,1

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
    # Scale to fill 9:16, center-crop, burn Portuguese subtitles; no branding/watermark.
    escaped_ass = str(ass).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    vf = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles='{escaped_ass}'"
    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
        "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output),
    ], timeout=1800)
    return output


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
            outputs.append({
                "name": output.name,
                "url": f"/api/jobs/{job_id}/files/{output.name}",
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


def new_job(source: Path, folder: Path, background: BackgroundTasks) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0, "message": "Na fila de processamento…", "clips": []}
    background.add_task(process_job, job_id, source, folder)
    return {"id": job_id, "status": "queued", "status_url": f"/api/jobs/{job_id}"}


@app.get("/health")
def health():
    return {"ok": True, "service": "WenClips Engine", "version": "0.1.0"}


def process_url_job(job_id: str, url: str, folder: Path) -> None:
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
