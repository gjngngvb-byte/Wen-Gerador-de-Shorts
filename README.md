# Wen Gerador de Shorts

Aplicação web para transformar vídeos em clipes verticais com legendas em português, cortes sugeridos automaticamente e exportação MP4 sem marca-d'água.

## O motor já incluído

O serviço em `engine/` usa:
- **FastAPI** para receber vídeos e expor uma API de trabalhos.
- **yt-dlp** para obter vídeos do YouTube quando o usuário tem autorização para baixar e reutilizar o conteúdo.
- **FFmpeg** para renderizar clipes MP4 verticais 9:16, preservando áudio e incorporando legendas.
- **faster-whisper** para transcrever fala em português localmente, sem uma API paga por minuto.
- Um ranqueador heurístico de transcrições para sugerir até cinco trechos. As sugestões são automáticas, mas não substituem uma revisão humana.

A interface já aceita links e uploads, acompanha o progresso e exibe links para baixar os clipes quando a API está conectada.

## Executar localmente

Requisitos: Node.js 20+, Python 3.11+, FFmpeg e fontes DejaVu instaladas.

Terminal 1, motor:

```bash
cd engine
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Terminal 2, site:

```bash
npm install
# Windows PowerShell:
$env:NEXT_PUBLIC_ENGINE_URL="http://localhost:8000"
# macOS/Linux:
# export NEXT_PUBLIC_ENGINE_URL=http://localhost:8000
npm run dev
```

Abra http://localhost:3000. Verifique o motor em http://localhost:8000/health.

## Hospedagem

O arquivo `render.yaml` prepara o serviço Docker para Render. Para colocar o motor online:

1. Crie um serviço no Render usando este repositório e o Blueprint `render.yaml`.
2. Depois do deploy, abra `https://SUA-API.onrender.com/health` e confirme que retorna JSON com `"ok": true`.
3. No projeto do site na Vercel, configure a variável de ambiente `NEXT_PUBLIC_ENGINE_URL` com a URL HTTPS do serviço Render, sem barra no final.
4. Em `ALLOWED_ORIGINS` no Render, informe a origem exata do site, por exemplo `https://seu-site.vercel.app` (sem caminho). Inclua `http://localhost:3000` se precisar testar localmente.
5. Faça novo deploy do site para a variável de ambiente entrar no bundle.

Planos gratuitos podem dormir, limitar CPU, tempo de execução e espaço temporário. O armazenamento usado por este protótipo é temporário: arquivos e trabalhos podem desaparecer quando o serviço reiniciar. Para produção, adicione uma fila persistente e armazenamento de objetos.

## API

- `GET /health`: status do motor.
- `POST /api/jobs/url`: JSON `{"url":"https://www.youtube.com/watch?v=..."}`.
- `POST /api/jobs/upload`: multipart com o campo `file` (limite padrão 500 MB).
- `GET /api/jobs/{id}`: estado, progresso e clipes gerados.
- `GET /api/jobs/{id}/files/{filename}`: baixa um MP4 gerado.

Estados do trabalho: `queued`, `downloading`, `processing`, `completed` e `failed`.

## Gratuidade e limites

O código usa ferramentas open source e não adiciona marca-d'água. Isso não torna a computação online ilimitada: transcrição e renderização consomem CPU, e hospedagens gratuitas podem suspender o serviço ou impor limites. O modelo `tiny` é escolhido para reduzir o consumo; qualidade e velocidade variam conforme o vídeo e o hardware.

## Uso responsável

Processe apenas vídeos que você possui ou tem autorização para baixar e reutilizar. Respeite os termos da plataforma e os direitos autorais. O motor não contorna vídeos privados, paywalls ou controles de acesso.
