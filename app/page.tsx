"use client";

import { useState } from "react";
import { ArrowDownToLine, ArrowRight, Captions, Check, Clapperboard, Clock3, FileVideo2, Link2, Scissors, Sparkles, Upload, WandSparkles } from "lucide-react";

export default function Home() {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<"link" | "upload">("link");
  const [notice, setNotice] = useState("");
  const [fileName, setFileName] = useState("");

  function submitLink(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const valid = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(url.trim());
    if (!valid) {
      setNotice("Cole um link válido do YouTube (youtube.com ou youtu.be).");
      return;
    }
    setNotice("Interface inicial pronta. O motor de processamento será conectado na próxima etapa; nenhum vídeo foi baixado ou processado ainda.");
  }

  return (
    <main>
      <nav className="nav wrap">
        <a className="brand" href="#"><span className="brand-icon"><Clapperboard size={21} /></span><span>Wen<span className="brand-accent">Clips</span></span></a>
        <div className="nav-right"><span className="free-pill"><span /> 100% código aberto</span><a className="github-link" href="https://github.com/gjngngvb-byte/Wen-Gerador-de-Shorts" target="_blank" rel="noreferrer">Ver no GitHub <ArrowRight size={15}/></a></div>
      </nav>

      <section className="hero wrap">
        <div className="eyebrow"><Sparkles size={14}/> SEU ESTÚDIO DE CLIPES COM IA</div>
        <h1>Vídeos longos.<br/><span>Momentos gigantes.</span></h1>
        <p className="hero-copy">Transforme vídeos em Shorts com cortes inteligentes, legendas dinâmicas e formato vertical. Sem assinatura. Sem marca-d’água.</p>

        <div className="creator-card">
          <div className="tabs" role="tablist" aria-label="Fonte do vídeo">
            <button className={mode === "link" ? "tab active" : "tab"} onClick={() => { setMode("link"); setNotice(""); }} type="button"><Link2 size={16}/> Link do YouTube</button>
            <button className={mode === "upload" ? "tab active" : "tab"} onClick={() => { setMode("upload"); setNotice(""); }} type="button"><Upload size={16}/> Enviar vídeo</button>
          </div>
          {mode === "link" ? (
            <form onSubmit={submitLink}>
              <label htmlFor="youtube-url">LINK DO VÍDEO</label>
              <div className="url-field"><Link2 size={18}/><input id="youtube-url" value={url} onChange={e => {setUrl(e.target.value); setNotice("");}} placeholder="https://www.youtube.com/watch?v=..." inputMode="url" /><button className="primary-btn" type="submit">Criar clipes <ArrowRight size={16}/></button></div>
              <p className="field-hint">Cole o link de um vídeo público. Use conteúdo que você tenha autorização para reutilizar.</p>
            </form>
          ) : (
            <div className="upload-zone">
              <input id="video-file" className="hidden-input" type="file" accept="video/*" onChange={e => { const f=e.target.files?.[0]; setFileName(f?.name ?? ""); setNotice(f ? "Arquivo selecionado. O processamento será conectado na próxima etapa." : ""); }} />
              <label htmlFor="video-file" className="upload-label"><span className="upload-icon"><FileVideo2 size={25}/></span><strong>{fileName || "Escolha um vídeo para começar"}</strong><span>MP4, MOV, WEBM e outros formatos compatíveis</span><span className="browse-btn">Selecionar arquivo</span></label>
            </div>
          )}
          {notice && <div className="notice" role="status">{notice}</div>}
          <div className="card-foot"><span><Check size={14}/> Sem marca-d’água</span><span><Check size={14}/> Legendas em português</span><span><Check size={14}/> Exportação vertical 9:16</span></div>
        </div>
        <div className="trust-note"><span className="pulse-dot"/> Projeto aberto e gratuito. O processamento real ainda está em construção.</div>
      </section>

      <section className="features wrap">
        <div className="section-heading"><span>DO LONGO AO CURTO</span><h2>Seu fluxo de edição, em um só lugar.</h2><p>O objetivo: automatizar as tarefas repetitivas e deixar você no controle do resultado.</p></div>
        <div className="feature-grid">
          <article className="feature"><div className="feature-icon violet"><WandSparkles size={21}/></div><h3>Momentos relevantes</h3><p>Transcrição e análise para sugerir trechos interessantes, não apenas cortes aleatórios.</p><span className="feature-status"><Clock3 size={13}/> Em desenvolvimento</span></article>
          <article className="feature"><div className="feature-icon blue"><Captions size={21}/></div><h3>Legendas sincronizadas</h3><p>Legendas em português com estilos legíveis para Shorts, Reels e TikTok.</p><span className="feature-status"><Clock3 size={13}/> Em desenvolvimento</span></article>
          <article className="feature"><div className="feature-icon orange"><Scissors size={21}/></div><h3>Cortes verticais</h3><p>Clipes 9:16 com reenquadramento e exportação MP4 sem marca-d’água.</p><span className="feature-status"><Clock3 size={13}/> Em desenvolvimento</span></article>
        </div>
      </section>

      <section className="how wrap">
        <div><span className="mini-label">SIMPLES POR DESIGN</span><h2>Da URL ao Short.<br/>Sem complicação.</h2></div>
        <div className="steps"><div className="step"><span>01</span><div><strong>Adicione seu vídeo</strong><p>Cole um link compatível ou envie um arquivo.</p></div></div><div className="step"><span>02</span><div><strong>Revise os destaques</strong><p>O sistema vai sugerir os trechos e as legendas para você ajustar.</p></div></div><div className="step"><span>03</span><div><strong>Exporte seus clipes</strong><p>Baixe os arquivos em MP4 prontos para revisar e publicar.</p></div></div></div>
      </section>

      <footer className="footer"><div className="wrap footer-inner"><a className="brand" href="#"><span className="brand-icon"><Clapperboard size={19}/></span><span>Wen<span className="brand-accent">Clips</span></span></a><span>Feito para criar. Aberto para todos.</span><a href="https://github.com/gjngngvb-byte/Wen-Gerador-de-Shorts" target="_blank" rel="noreferrer">Código-fonte <ArrowDownToLine size={14}/></a></div></footer>
    </main>
  );
}