# Video Downloader Telegram Bot

Bot de download de vídeos para Telegram usando yt-dlp. Suporta +1000 sites incluindo YouTube, TikTok, Instagram, Facebook, Twitter/X, Twitch e muitos outros.

**📦 Limite de 2GB por arquivo** via self-hosted Bot API Server.

## Funcionalidades

- **+1000 sites suportados** via yt-dlp
- **Arquivos até 2GB** (self-hosted Bot API)
- **Múltiplas qualidades**: Melhor, 1080p, 720p, 480p, MP3
- **Interface inline** com botões para seleção de qualidade
- **Envio automático** do arquivo baixado

## Início Rápido

### 1. Obter credenciais

#### Bot Token (@BotFather)
1. Abra o [@BotFather](https://t.me/BotFather) no Telegram
2. Envie `/newbot`
3. Siga as instruções para criar o bot
4. Copie o **token** fornecido

#### API ID e API Hash (my.telegram.org)
1. Acesse [my.telegram.org/auth](https://my.telegram.org/auth)
2. Entre com seu número de telefone
3. Vá em "API development tools"
4. Crie uma nova aplicação
5. Copie o **api_id** e **api_hash**

### 2. Configurar e Executar

```bash
# Criar arquivo .env
cp .env.example .env

# Editar .env com suas credenciais
# BOT_TOKEN=seu_token_aqui
# API_ID=12345678
# API_HASH=suahashaqui

# Subir o bot com Docker (rebuild para atualizar)
docker compose up -d --build
```

### 3. Usar o Bot

1. Abra seu bot no Telegram
2. Envie `/start`
3. Cole a URL do vídeo
4. Selecione a qualidade desejada
5. Aguarde o download e receba o arquivo!

## Estrutura do Projeto

```
.
├── .env.example      # Template de variáveis de ambiente
├── bot.py            # Bot do Telegram
├── docker-compose.yml # Orquestração dos serviços
├── Dockerfile        # Container do bot
├── Dockerfile.api    # Self-hosted Bot API Server
├── requirements.txt  # Dependências Python
└── downloads/        # Arquivos baixados (volume)
```

## Verificar se está funcionando

```bash
# Ver logs do bot
docker compose logs -f telegram-bot

# Você deve ver:
# ✅ Bot API Server: http://telegram-bot-api:8081/bot
# ✅ Limite de arquivo: 2GB

# Se ver isso, está usando API pública (50MB):
# ⚠️ Usando Bot API pública (limite 50MB)
```

## Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `BOT_TOKEN` | ✅ | Token do bot (do @BotFather) |
| `API_ID` | ✅ | API ID (do my.telegram.org) |
| `API_HASH` | ✅ | API Hash (do my.telegram.org) |
| `DOWNLOADS_DIR` | ❌ | Diretório para arquivos (padrão: `/downloads`) |
| `BOT_API_URL` | ❌ | URL do Bot API Server (automático no Docker) |

## Comandos do Bot

| Comando | Descrição |
|---------|-----------|
| `/start` | Iniciar o bot e ver mensagem de boas-vindas |
| `/help` | Ver instruções de uso |
| `/jobs` | Ver seus downloads recentes |

## Qualidades Disponíveis

| Opção | Descrição | Tamanho Estimado |
|-------|-----------|------------------|
| 🎬 Melhor | Máxima qualidade disponível | Maior |
| 📺 1080p | Full HD (1920×1080) | Grande |
| 📺 720p | HD (1280×720) | Médio |
| 📺 480p | SD (854×480) | Menor |
| 🎵 MP3 | Apenas áudio em MP3 192kbps | Menor |

## Sites Suportados

O yt-dlp suporta mais de 1000 sites. Principais:

| Plataforma | Observações |
|-----------|-------------|
| YouTube | Vídeos, Shorts, lives |
| TikTok | Vídeos públicos |
| Instagram | Posts, Reels (conta pública) |
| Facebook | Vídeos públicos |
| Twitter / X | Vídeos em tweets públicos |
| Twitch | VODs e clips |
| Vimeo | Vídeos públicos |
| Reddit | Vídeos hospedados |
| SoundCloud | Áudios (use MP3) |

## Troubleshooting

### Bot mostra limite de 50MB

Isso significa que o Bot API Server não está sendo usado. Verifique:

```bash
# 1. Verificar se o container está rodando
docker compose ps

# 2. Ver logs do Bot API Server
docker compose logs telegram-bot-api

# 3. Ver logs do bot
docker compose logs telegram-bot

# 4. Reconstruir tudo
docker compose down
docker compose up -d --build
```

### Erro no download

- Alguns sites podem bloquear downloads
- Tente qualidade diferente
- Verifique se a URL é válida

### Arquivo não enviado

- Verifique se excede 2GB
- Verifique os logs do bot

## Executar sem Docker

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis
export BOT_TOKEN=seu_token_aqui
export API_ID=12345678
export API_HASH=suahashaqui

# Executar
python bot.py
```

> ⚠️ Sem o self-hosted Bot API Server, o limite é de 50MB.

## Licença

MIT
