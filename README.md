# Raspberry Pi Timelapse Bot 🎥

A simple **timelapse daemon** for Raspberry Pi + USB webcam.  
It captures frames periodically, generates daily MP4s, and sends them to **Telegram**.  
It also maintains a **master timelapse** by merging daily videos.

## ✨ Features
- Capture images every `N` seconds.
- Organize photos into `/data/images/YYYY-MM-DD`.
- Build daily MP4 with `ffmpeg`.
- Send videos automatically to Telegram.
- Maintain a master timelapse (`master.mp4`).
- Basic Telegram command:
  - `/status` → check if the bot is running.

## 🚀 Run with Docker Compose

```bash
git clone https://github.com/bruuzaki/timelapse-bot.git
cd timelapse-bot
cp .env.example .env
# Edit .env with your Telegram bot token & chat ID
docker compose up -d

⚙️ Environment Variables
Variable	Default	Description
TIMELAPSE_BASE_DIR	/data	Where to store images & videos
CAPTURE_INTERVAL_SECONDS	300	Seconds between captures
TELEGRAM_BOT_TOKEN	(required)	Your Telegram bot token
TELEGRAM_CHAT_ID	(required)	Your Telegram chat ID

Made with ❤️ by Bruno (Bruuzaki)