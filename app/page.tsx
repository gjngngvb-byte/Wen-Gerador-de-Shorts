"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, ArrowRight, Captions, Check, Clapperboard, Clock3, FileVideo2, Link2, LoaderCircle, Scissors, Sparkles, Upload, WandSparkles, Download, AlertCircle } from "lucide-react";

type Clip = { name: string; url: string; start: number; end: number; duration: number };
type Job = { id: string; status: string; progress: number; message: string; error?: string; clips?: Clip[] };

const API_BASE = (process.env.NEXT_PUBLIC_ENGINE_URL || "").replace(/\/+$/, "");

export default function Home() {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<"link" | "upload">("link");
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  async function readError(response: Response) {
    try {
      const body = await response.json();
      return body.detail || body.error || ("Erro HTTP " + response.status);
    } catch {
      return "Erro HTTP " + response.status;
    }
  }

  function watchJob(jobId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    const check = async () => {
      try {
        const response = await fetch(API_BASE + "/api/jobs/" + jobId);
        if (!response.ok) throw new Error(await readError(response));
        const data: Job = await response.json();
        setJob(data);
        if (data.status === "completed" || data.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setBusy(false);
          if (data.status === "failed") setNotice(data.error || data.message || "O processamento falhou.");
          else setNotice("Pronto! Seus clipes estão abaixo.");
        }
      } catch (error) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setBusy(false);
        setNotice(error instanceof Error ? error.message : "Não foi possível consultar o processamento.");
      }
    };
    pollRef.current = setInterval(check, 2500);
    void check();
  }

  async function submitLink(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setNotice("");
    setJob(null);
    if (!API_BASE) {
      setNotice("O motor ainda não está conectado a uma hospedagem. Configure NEXT_PUBLIC_ENGINE_URL com a URL pública da API para processar vídeos.");
      return;
    }
    if (!/^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(url.trim())) {
      setNotice("Cole um link válido do YouTube (youtube.com ou youtu.be).");
      return;
    }
    setBusy(true);
    setNotice("Enviando o trabalho para o motor…");
    try {
      const response = await fetch(API_BASE + "/api/jobs/url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setJob({ id: data.id, status: data.status, progress: 3, message: "Trabalho enviado. Preparando o vídeo…" });
      watchJob(data.id);
    } catch (error) {
      setBusy(false);
      setNotice(error instanceof Error ? error.message : "Não consegui conectar ao motor. Confira se a API está no ar.");
    }
  }

  async function submitUpload() {
    setNotice("");
    setJob(null);
    if (!API_BASE) {
      setNotice("O motor ainda não está conectado a uma hospedagem. Configure NEXT_PUBLIC_ENGINE_URL com a URL pública da API para processar vídeos.");
      return;
    }
    if (!file) {
      setNotice("Primeiro selecione um arquivo de vídeo.");
      return;
    }
    setBusy(true);
    setNotice("Enviando seu vídeo…");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(API_BASE + "/api/jobs/upload", { method: "POST", body: form });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      setJob({ id: data.id, status: data.status, progress: 0, message: "Vídeo enviado. Preparando o processamento…" });
      watchJob(data.id);
    } catch (error) {
      setBusy(false);
      setNotice(error instanceof Error ? error.message : "Não consegui enviar o vídeo.");
    }
  }

  return (
    <main>
      <nav className="nav wrap">
        <a className="brand" href="#"><span className="brand-icon"><Clapperboard size={21} /></span><span>Wen<span className="brand-accent">Clips</span></span></a>
        <div className="nav-right"><span className="free-pill"><span /> Código aberto</span><a className="github-link" href="https://github.com/gjngngvb-byte/Wen-Gerador-de-Shorts" target="_blank" rel="noreferrer">Ver no GitHub <ArrowRight size={15}/></a></div>
      </nav>

      <section className="hero wrap">
        <div className="eyebrow"><Sparkles size={14}/> SEU ESTÚDIO DE CLIPES COM IA</div>
        <h1>Vídeos longos.<br/><span>Momentos gigantes.</span></h1>
        <p className="hero-copy">Transforme vídeos em Shorts com cortes sugeridos pela transcrição, legendas em português e formato vertical. Sem marca-d’água.</p>

        <div className="creator-card">
          <div className="tabs" role="tablist" aria-label="Fonte do vídeo">
            <button className={mode === "link" ? "tab active" : "tab"} onClick={() => { setMode("link"); setNotice(""); }} type="button"><Link2 size={16}/> Link do YouTube</button>
            <button className={mode === "upload" ? "tab active" : "tab"} onClick={() => { setMode("upload"); setNotice(""); }} type="button"><Upload size={16}/> Enviar vídeo</button>
          </div>
          {mode === "link" ? (
            <form onSubmit={submitLink}>
              <label htmlFor="youtube-url">LINK DO VÍDEO</label>
              <div className="url-field"><Link2 size={18}/><input id="youtube-url" value={url} onChange={e => {setUrl(e.target.value); setNotice("");}} placeholder="https://www.youtube.com/watch?v=..." inputMode="url" disabled={busy} /><button className="primary-btn" type="submit" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={16}/> Processando</> : <>Criar clipes <ArrowRight size={16}/></>}</button></div>
              <p className="field-hint">Use vídeos seus ou que você tenha autorização para baixar e reutilizar.</p>
            </form>
          ) : (
            <div className="upload-zone">
              <input id="video-file" className="hidden-input" type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo" disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); setNotice(""); }} />
              <label htmlFor="video-file" className="upload-label"><span className="upload-icon"><FileVideo2 size={25}/></span><strong>{file?.name || "Escolha um vídeo para começar"}</strong><span>MP4, MOV, WEBM, MKV ou AVI. Limite padrão: 500 MB.</span><span className="browse-btn">Selecionar arquivo</span></label>
              <button className="primary-btn upload-submit" type="button" onClick={submitUpload} disabled={busy || !file}>{busy ? <><LoaderCircle className="spin" size={16}/> Enviando</> : <>Gerar clipes <ArrowRight size={16}/></>}</button>
            </div>
          )}
          {notice && <div className={"notice " + (job?.status === "failed" ? "notice-error" : "")} role="status">{job?.status === "failed" && <AlertCircle size={16}/>}<span>{notice}</span></div>}
          {job && busy && <div className="job-progress" aria-live="polite"><div className="job-progress-top"><span><LoaderCircle className="spin" size={15}/> {job.message}</span><strong>{job.progress}%</strong></div><div className="progress-track"><span style={{width: Math.max(3, job.progress) + "%"}} /></div><small>Deixe esta página aberta enquanto o motor trabalha. Vídeos longos podem demorar.</small></div>}
          {job?.status === "completed" && job.clips && job.clips.length > 0 && <div className="results"><h3><Check size={18}/> Seus clipes estão prontos</h3><div className="clip-list">{job.clips.map((clip, index) => <div className="clip-item" key={clip.name}><div className="clip-number">{String(index + 1).padStart(2, "0")}</div><div className="clip-info"><strong>Short {index + 1}</strong><span>{Math.round(clip.duration)} s · trecho {Math.floor(clip.start / 60)}:{String(Math.floor(clip.start % 60)).padStart(2, "0")}</span></div><a className="download-btn" href={API_BASE + clip.url}><Download size={16}/> Baixar MP4</a></div>)}</div><p className="field-hint">Os destaques são sugestões automáticas. Assista e revise antes de publicar.</p></div>}
          <div className="card-foot"><span><Check size={14}/> Sem marca-d’água</span><span><Check size={14}/> Legendas em português</span><span><Check size={14}/> Exportação vertical 9:16</span></div>
        </div>
        <div className="trust-note"><span className="pulse-dot"/> Motor open source. A URL pública da API precisa estar configurada para gerar vídeos.</div>
      </section>

      <section className="features wrap">
        <div className="section-heading"><span>DO LONGO AO CURTO</span><h2>Seu fluxo de edição, em um só lugar.</h2><p>O motor usa transcrição para sugerir trechos, gera legendas e exporta vídeos verticais.</p></div>
        <div className="feature-grid">
          <article className="feature"><div className="feature-icon violet"><WandSparkles size={21}/></div><h3>Momentos relevantes</h3><p>Analisa a transcrição e prioriza trechos com fala, ênfase e frases que podem render bons destaques.</p><span className="feature-status"><Check size={13}/> Motor implementado</span></article>
          <article className="feature"><div className="feature-icon blue"><Captions size={21}/></div><h3>Legendas sincronizadas</h3><p>Transcrição em português e legendas embutidas, legíveis no celular.</p><span className="feature-status"><Check size={13}/> Motor implementado</span></article>
          <article className="feature"><div className="feature-icon orange"><Scissors size={21}/></div><h3>Cortes verticais</h3><p>Renderização MP4 em 9:16, sem marca-d’água, com áudio e legendas.</p><span className="feature-status"><Check size={13}/> Motor implementado</span></article>
        </div>
      </section>

      <section className="how wrap">
        <div><span className="mini-label">SIMPLES POR DESIGN</span><h2>Da URL ao Short.<br/>Sem complicação.</h2></div>
        <div className="steps"><div className="step"><span>01</span><div><strong>Adicione seu vídeo</strong><p>Cole um link autorizado ou envie um arquivo de vídeo.</p></div></div><div className="step"><span>02</span><div><strong>Deixe o motor trabalhar</strong><p>Ele transcreve, seleciona os trechos e cria as legendas.</p></div></div><div className="step"><span>03</span><div><strong>Baixe e revise</strong><p>Exporte os clipes em MP4 vertical antes de publicar.</p></div></div></div>
      </section>

      <footer className="footer"><div className="wrap footer-inner"><a className="brand" href="#"><span className="brand-icon"><Clapperboard size={19}/></span><span>Wen<span className="brand-accent">Clips</span></span></a><span>Feito para criar. Aberto para todos.</span><a href="https://github.com/gjngngvb-byte/Wen-Gerador-de-Shorts" target="_blank" rel="noreferrer">Código-fonte <ArrowDownToLine size={14}/></a></div></footer>
    </main>
  );
}
