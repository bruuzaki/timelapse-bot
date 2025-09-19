"""
timelapse.py
Timelapse daemon for Raspberry Pi + USB webcam.
Features:
- Capture frames periodically and save into /data/images/YYYY-MM-DD.
- At midnight, build a daily MP4 (ffmpeg).
- Send daily video and an updated master to Telegram.
- Basic Telegram command support (/status).

Author: Bruno (Bruuzaki)
"""

import os
import time
import datetime
import subprocess
import logging
import threading
from pathlib import Path
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
import cv2

# -----------------------
# CONFIG
# -----------------------
DEFAULTS = {
    "BASE_DIR": Path(os.environ.get("TIMELAPSE_BASE_DIR", "/data")),
    "CAPTURE_INTERVAL_SECONDS": int(os.environ.get("CAPTURE_INTERVAL_SECONDS", "300")),
    "FRAME_WIDTH": int(os.environ.get("FRAME_WIDTH", "1280")),
    "FRAME_HEIGHT": int(os.environ.get("FRAME_HEIGHT", "720")),
    "DAILY_FPS": int(os.environ.get("DAILY_FPS", "30")),
    "VIDEO_CODEC": os.environ.get("VIDEO_CODEC", "libx264"),
    "VIDEO_PRESET": os.environ.get("VIDEO_PRESET", "ultrafast"),
    "CRF": os.environ.get("CRF", "23"),
    "CAM_INDEX": int(os.environ.get("CAM_INDEX", "0")),
    "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
    "MAX_TELEGRAM_MB": int(os.environ.get("MAX_TELEGRAM_MB", "400")),
}

BASE_DIR: Path = Path(DEFAULTS["BASE_DIR"])
VIDEOS_DIR = BASE_DIR / "videos"
IMAGES_DIR = BASE_DIR / "images"
for p in (BASE_DIR, VIDEOS_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("timelapse")

# -----------------------
# ffmpeg helpers
# -----------------------
def make_video_from_images(day_dir: Path, out_mp4: Path, fps: int = DEFAULTS["DAILY_FPS"]):
    logger.info(f"Making video for {day_dir} -> {out_mp4}")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-start_number", "1",
        "-i", str(day_dir / "%06d.jpg"),
        "-c:v", DEFAULTS["VIDEO_CODEC"],
        "-preset", DEFAULTS["VIDEO_PRESET"],
        "-crf", DEFAULTS["CRF"],
        "-pix_fmt", "yuv420p",
        str(out_mp4)
    ]
    subprocess.run(cmd, check=True)

def concat_videos_fast(video_paths, outpath: Path):
    logger.info(f"Concat {len(video_paths)} videos -> {outpath}")
    ts_files = []
    try:
        for v in video_paths:
            ts = v.with_suffix(".ts")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(v), "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts", str(ts)],
                check=True
            )
            ts_files.append(str(ts))
        concat_input = "concat:" + "|".join(ts_files)
        subprocess.run(
            ["ffmpeg", "-y", "-i", concat_input, "-c", "copy", "-bsf:a", "aac_adtstoasc", str(outpath)],
            check=True
        )
    finally:
        for p in ts_files:
            try: os.remove(p)
            except: pass

def merge_daily_into_master(master_path: Path, day_video_path: Path):
    if not master_path.exists():
        subprocess.run(["cp", str(day_video_path), str(master_path)], check=True)
        return master_path
    temp_out = master_path.with_suffix(".new.mp4")
    concat_videos_fast([master_path, day_video_path], temp_out)
    os.replace(temp_out, master_path)
    return master_path

# -----------------------
# Telegram helpers
# -----------------------
def send_file_telegram(file_path: Path, caption: str = ""):
    bot_token = DEFAULTS["TELEGRAM_BOT_TOKEN"]
    chat_id = DEFAULTS["TELEGRAM_CHAT_ID"]
    if not bot_token or not chat_id:
        logger.warning("Telegram not configured.")
        return
    filesize_mb = file_path.stat().st_size / 1024 / 1024
    if filesize_mb > DEFAULTS["MAX_TELEGRAM_MB"]:
        logger.warning(f"Skipping send, file {filesize_mb:.1f}MB too large")
        return
    bot = Bot(token=bot_token)
    with file_path.open("rb") as fh:
        bot.send_video(chat_id=chat_id, video=fh, caption=caption)
    logger.info(f"Sent {file_path.name} to Telegram")

# -----------------------
# Capture daemon
# -----------------------
class TimelapseDaemon:
    def __init__(self):
        self.cap = None
        self.seq = 1
        self.running = False
        self.width = DEFAULTS["FRAME_WIDTH"]
        self.height = DEFAULTS["FRAME_HEIGHT"]
        self.interval = DEFAULTS["CAPTURE_INTERVAL_SECONDS"]
        self.current_day = datetime.date.today()
        self.current_dir = IMAGES_DIR / self.current_day.isoformat()
        self.current_dir.mkdir(parents=True, exist_ok=True)

    def open_cam(self):
        logger.info(f"Opening camera index {DEFAULTS['CAM_INDEX']}")
        self.cap = cv2.VideoCapture(DEFAULTS["CAM_INDEX"])
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        time.sleep(1)
        ret, _ = self.cap.read()
        if not ret:
            raise RuntimeError("Camera not accessible.")

    def capture_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            logger.warning("Failed to capture frame.")
            return
        filename = self.current_dir / f"{self.seq:06d}.jpg"
        cv2.imwrite(str(filename), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        logger.info(f"📸 Captured {filename}")
        self.seq += 1

    def finalize_day_async(self, day: datetime.date, dirpath: Path):
        def job():
            try:
                day_str = day.isoformat()
                out_mp4 = VIDEOS_DIR / f"{day_str}.mp4"
                make_video_from_images(dirpath, out_mp4)
                send_file_telegram(out_mp4, caption=f"Timelapse {day_str}")
                master = VIDEOS_DIR / "master.mp4"
                merge_daily_into_master(master, out_mp4)
                send_file_telegram(master, caption=f"Updated master after {day_str}")
            except Exception as e:
                logger.exception("Error finalizing day: " + str(e))
        threading.Thread(target=job, daemon=True).start()

    def run(self):
        self.running = True
        self.open_cam()
        logger.info("Timelapse daemon started. Ctrl+C to stop.")
        try:
            while self.running:
                now = datetime.date.today()
                if now != self.current_day:
                    self.finalize_day_async(self.current_day, self.current_dir)
                    self.current_day = now
                    self.current_dir = IMAGES_DIR / now.isoformat()
                    self.current_dir.mkdir(parents=True, exist_ok=True)
                    self.seq = 1
                self.capture_frame()
                for _ in range(self.interval):
                    time.sleep(1)
                    if datetime.date.today() != self.current_day:
                        break
        except KeyboardInterrupt:
            logger.info("Stopping by user request.")
        finally:
            self.running = False
            if self.cap: self.cap.release()

# -----------------------
# Telegram command (/status)
# -----------------------
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"Timelapse running.\nCurrent day: {datetime.date.today()}\nNext capture every {DEFAULTS['CAPTURE_INTERVAL_SECONDS']}s."
    await update.message.reply_text(msg)

# -----------------------
# main
# -----------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run capture daemon")
    args = parser.parse_args()

    if args.run:
        daemon = TimelapseDaemon()
        t = threading.Thread(target=daemon.run, daemon=True)
        t.start()

        if DEFAULTS["TELEGRAM_BOT_TOKEN"]:
            app = Application.builder().token(DEFAULTS["TELEGRAM_BOT_TOKEN"]).build()
            app.add_handler(CommandHandler("status", status))
            app.run_polling()
        else:
            t.join()
