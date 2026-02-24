# Video Downloader Bot

Bot de download de vídeos com FastAPI, yt-dlp e SSE para progresso em tempo real.

## Funcionalidades

- **+1000 sites suportados** via yt-dlp (YouTube, TikTok, Instagram, Twitter, etc.)
- **Progresso em tempo real** via Server-Sent Events (SSE)
- **Múltiplas qualidades**: Melhor, 1080p, 720p, 480p, MP3
- **Player inline** para visualização antes do download
- **Thumbnail e título** extraídos automaticamente
- **Docker pronto** para deploy fácil

## Estrutura do Projeto

```
downloader-bot/
├── docker-compose.yml    # Orquestração do serviço
├── Dockerfile            # Definição do container
├── requirements.txt      # Dependências Python
├── main.py               # Aplicação FastAPI
├── static/
│   └── index.html        # Interface web
└── downloads/            # Arquivos baixados (volume)
```

## Início Rápido

### Com Docker (Recomendado)

```bash
# Subir o bot
docker compose up -d --build

# Acessar interface web
open http://localhost:8000
```

### Sem Docker

```bash
# Instalar dependências
pip install -r requirements.txt

# Executar
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Uso via API

### Criar um download

```bash
curl -X POST http://localhost:8000/api/jobs/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "quality": "720p"}'
```

Resposta:
```json
{"id": "a1b2c3d4", "status": "queued"}
```

### Acompanhar progresso (SSE)

```bash
curl -N http://localhost:8000/api/jobs/a1b2c3d4/stream
```

### Listar todos os jobs

```bash
curl http://localhost:8000/api/jobs
```

### Obter detalhes de um job

```bash
curl http://localhost:8000/api/jobs/a1b2c3d4
```

### Baixar o arquivo

```bash
curl http://localhost:8000/api/jobs/a1b2c3d4/download-file -o video.mp4
```

## Endpoints da API

| Método | Path | Descrição |
|--------|------|-----------|
| POST | `/api/jobs/download` | Criar novo job de download |
| GET | `/api/jobs` | Listar todos os jobs |
| GET | `/api/jobs/{jid}` | Obter detalhes de um job |
| GET | `/api/jobs/{jid}/stream` | SSE com progresso em tempo real |
| GET | `/api/jobs/{jid}/download-file` | Baixar arquivo concluído |

## Qualidades Disponíveis

| Opção | Descrição |
|-------|-----------|
| `best` | Melhor qualidade disponível (padrão) |
| `1080p` | Máximo 1080p |
| `720p` | Máximo 720p |
| `480p` | Máximo 480p |
| `audio` | Apenas áudio em MP3 |

## Estados do Job

| Status | Descrição |
|--------|-----------|
| `queued` | Job na fila, aguardando início |
| `running` | Download em andamento |
| `done` | Download concluído com sucesso |
| `error` | Erro durante o download |

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `DOWNLOADS_DIR` | `/downloads` | Diretório para salvar arquivos |

## Requisitos

- Docker e Docker Compose
- Ou Python 3.12+ com ffmpeg instalado

## Licença

MIT
