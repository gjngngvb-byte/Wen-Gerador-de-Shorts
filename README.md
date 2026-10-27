# Wen Gerador de Shorts

Aplicação web para transformar vídeos em clipes verticais com legendas, cortes e exportação sem marca-d'água.

## Objetivo
- Receber URL de vídeo do YouTube e arquivos enviados pelo usuário.
- Preparar transcrição e identificar trechos interessantes.
- Gerar clipes 9:16 com legendas e exportação MP4.
- Disponibilizar uma API própria para integração.

## Estado atual
O repositório está sendo iniciado. A primeira etapa é a interface web e a arquitetura de processamento. O processamento de vídeo exige um backend/worker com FFmpeg e modelos de transcrição; hospedagens serverless gratuitas não são adequadas para tarefas longas.

## Desenvolvimento
Requisitos: Node.js 20+ e pnpm/npm.

```bash
npm install
npm run dev
```

## Gratuidade
O projeto usa ferramentas de código aberto. Hospedagem, armazenamento, largura de banda e modelos externos podem ter limites ou custos. O objetivo é evitar APIs pagas por vídeo e marca-d'água.

## Uso responsável
Processe vídeos que você possui ou tem autorização para baixar e reutilizar. Respeite os termos da plataforma e os direitos autorais.