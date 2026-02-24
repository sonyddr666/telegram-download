# Video Downloader Telegram Bot

Bot de download de vídeos para Telegram usando yt-dlp. Suporta +1000 sites incluindo YouTube, TikTok, Instagram, Facebook, Twitter/X, Twitch e muitos outros.

## Funcionalidades

- **+1000 sites suportados** via yt-dlp
- **Múltiplas qualidades**: Melhor, 1080p, 720p, 480p, MP3
- **Interface inline** com botões para seleção de qualidade
- **Envio automático** do arquivo baixado
- **Limite de 50MB** (restrição do Telegram)

## Início Rápido

### 1. Criar o Bot no Telegram

1. Abra o [@BotFather](https://t.me/BotFather) no Telegram
2. Envie `/newbot`
3. Siga as instruções para criar o bot
4. Copie o **token** fornecido

### 2. Configurar e Executar

```bash
# Clonar ou entrar no diretório
cd downloader-bot

# Criar arquivo .env com o token
echo "BOT_TOKEN=seu_token_aqui" > .env

# Subir o bot com Docker
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
downloader-bot/
├── docker-compose.yml    # Orquestração do serviço
├── Dockerfile            # Container com Python 3.12 + ffmpeg
├── requirements.txt      # python-telegram-bot, yt-dlp
├── bot.py                # Bot do Telegram
└── downloads/            # Arquivos baixados (volume)
```

## Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `BOT_TOKEN` | ✅ | Token do bot (do @BotFather) |
| `DOWNLOADS_DIR` | ❌ | Diretório para arquivos (padrão: `/downloads`) |

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

## Executar sem Docker

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar token
export BOT_TOKEN=seu_token_aqui

# Executar
python bot.py
```

## Limitações

- **Tamanho máximo**: 50MB por arquivo (limite do Telegram)
- **Vídeos maiores**: O bot avisará e sugerirá usar qualidade menor
- **Playlists**: Não suportado (apenas vídeos individuais)

## Dicas

- Para vídeos longos, use **480p** ou **MP3** para ficar dentro do limite
- Para músicas e podcasts, use **🎵 MP3**
- Se o download falhar, tente com qualidade **Melhor**

## Licença

MIT
