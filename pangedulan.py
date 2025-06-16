import logging
import os
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import json
import random
import time

USER_DATA_FILE = "user_data.json"

def load_local_user_data(chat_id: int) -> dict | None:
    if not os.path.exists(USER_DATA_FILE):
        return None
    try:
        with open(USER_DATA_FILE, 'r') as f:
            all_data = json.load(f)
            return all_data.get(str(chat_id))
    except json.JSONDecodeError:
        logging.error(f"Gagal memuat data dari {USER_DATA_FILE}. File mungkin kosong atau rusak.")
        return None
    except Exception as e:
        logging.error(f"Error saat memuat data pengguna {chat_id} dari lokal: {e}", exc_info=True)
        return None

def save_local_user_data(chat_id: int, data_to_save: dict):
    all_data = {}
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                all_data = json.load(f)
        except json.JSONDecodeError:
            logging.warning(f"File {USER_DATA_FILE} kosong atau rusak, membuat ulang.")
            all_data = {}

    all_data[str(chat_id)] = data_to_save
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(all_data, f, indent=4)
        logging.info(f"Data pengguna {chat_id} berhasil disimpan ke {USER_DATA_FILE}.")
    except Exception as e:
        logging.error(f"Gagal menyimpan data pengguna {chat_id} ke {USER_DATA_FILE}: {e}", exc_info=True)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.error(
        "FATAL: Variabel lingkungan 'GEMINI_API_KEY' tidak ditemukan. Pastikan ada di file .env")
    exit(1)

if not TELEGRAM_TOKEN:
    logger.error(
        "FATAL: Variabel lingkungan 'TELEGRAM_TOKEN' tidak ditemukan. Pastikan ada di file .env")
    exit(1)

try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
    logger.info(
        "Model Gemini 'gemini-2.5-flash-preview-05-20' berhasil diinisialisasi."
    )
except Exception as e:
    logger.error(
        f"Error saat konfigurasi API Key Gemini atau inisialisasi model: {e}")
    exit(1)

user_data = {}

MOODS = {
    "sumanget": {
        "greeting_extra":
        ["Kumaha damang, uy?", "Euy, aya naon ieu?"],
        "response_
