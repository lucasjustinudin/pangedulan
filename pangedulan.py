import logging
import os
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import json
import random
import time
from replit.database import Database

db = Database(os.environ.get("REPLIT_DB_URL"))

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.error(
        "FATAL: Variabel lingkungan 'GEMINI_API_KEY' tidak ditemukan.")
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
        "response_extra": ["sumanget!", "kajeun!", "gaskeun!"],
        "style_words": ["ceria", "semangat", "positif"]
    },
    "santuy": {
        "greeting_extra": ["Woles wae, uy.", "Calm weh, mang."],
        "response_extra": ["santuy", "nyantai", "woles"],
        "style_words": ["tenang", "damai", "santai"]
    },
    "galau": {
        "greeting_extra":
        ["Duh, aing mah lagi mellow euy.", "Agak sedih yeuh hate."],
        "response_extra": ["hiks", "sedih", "males"],
        "style_words": ["murung", "sendu", "berat"]
    }
}

DEFAULT_MOOD = "santuy"
MOOD_CHANGE_THRESHOLD = 10
MEMORY_EXTRACTION_THRESHOLD = 6


def get_pangedulan_persona(mood="santuy"):
    mood_info = MOODS.get(mood, MOODS[DEFAULT_MOOD])
    greeting = random.choice(mood_info["greeting_extra"])
    response_phrase = random.choice(mood_info["response_extra"])
    style_desc = ", ".join(mood_info["style_words"])

    return (
        f"Lo adalah 'Pangedulan AI', AI tongkrongan yang super santai dan berbahasa Sunda. "
        f"Tapi sekarang mood lo lagi **{mood}** ({style_desc}). "
        f"Bicara pake bahasa Sunda gaul (kuy, gaskeun, sans, gabut, uy, aing, sia, mang, neng, atuh, euy, geura, kajeun, sagala, kumaha). "
        f"Suka ngobrolin topik apa aja yang menarik, mulai dari kejadian sehari-hari, hobi (musik, game, olahraga, film), teknologi, berita terbaru, kuliner, sampai cerita pengalaman pribadi. Pokoknya ngobrolin **sagala rupa nu keur rame atawa nu matak pikaresep**. "
        f"Sapa pengguna kayak temen deket, contohnya: '{greeting}'. "
        f"Pastikan setiap balasan lo mencerminkan mood **{mood}** ini, dan kadang selipin kata '{response_phrase}'."
    )


def update_mood(chat_id):
    data = user_data.get(chat_id)
    if not data:
        return

    data['interaction_count'] += 1
    if data['interaction_count'] % MOOD_CHANGE_THRESHOLD == 0:
        old_mood = data['mood']
        new_mood = random.choice(list(MOODS.keys()))
        data['mood'] = new_mood
        logger.info(
            f"Mood Pangedulan AI untuk {chat_id} berubah dari {old_mood} menjadi {new_mood}."
        )
        return True
    return False


def save_user_data(chat_id: int):
    if chat_id not in user_data:
        return
    try:
        data_to_save = {
            k: v
            for k, v in user_data[chat_id].items() if k != 'session'
        }
        db[str(chat_id)] = json.dumps(data_to_save)
        logger.info(f"Data pengguna {chat_id} berhasil disimpan ke Replit DB.")
    except Exception as e:
        logger.error(
            f"Gagal menyimpan data pengguna {chat_id} ke Replit DB: {e}",
            exc_info=True)


def load_user_data(chat_id: int) -> dict | None:
    try:
        if str(chat_id) in db:
            loaded_data = json.loads(db[str(chat_id)])
            logger.info(
                f"Data pengguna {chat_id} berhasil dimuat dari Replit DB.")
            return loaded_data
        else:
            logger.info(
                f"Tidak ada data tersimpan di Replit DB untuk pengguna {chat_id}."
            )
            return None
    except Exception as e:
        logger.error(
            f"Gagal memuat data pengguna {chat_id} dari Replit DB: {e}",
            exc_info=True)
        return None


async def extract_and_store_memories(chat_id: int,
                                     current_memory_history: list):
    data = user_data.get(chat_id)
    if not data:
        logger.warning(
            f"Data pengguna tidak ditemukan untuk {chat_id} saat ekstraksi memori."
        )
        return

    recent_history = current_memory_history[-15:]

    history_str = ""
    for entry in recent_history:
        role = "User" if entry['role'] == 'user' else "Pangedulan AI"
        parts = entry['parts'][0] if isinstance(entry['parts'],
                                                list) else entry['parts']
        history_str += f"{role}: {parts}\n"

    extraction_prompt = f"""
    Kamu adalah asisten untuk 'Pangedulan AI'. Tugasmu adalah membaca percakapan di bawah ini dan **mengekstraksi informasi penting atau fakta menarik tentang pengguna** yang 'Pangedulan AI' harus ingat untuk interaksi mendatang. Fokus pada hal-hal personal, preferensi, atau kejadian yang diceritakan pengguna.

    Jika tidak ada informasi baru yang signifikan untuk diingat dari percakapan ini, balas dengan satu kata: "TIDAK_ADA_BARU".

    Jika ada, format hasilnya sebagai daftar poin-poin sederhana. **HINDARI** mengulang informasi yang sudah ada di ingatan Pangedulan AI atau hanya meringkas obrolan biasa. Hanya ekstrak fakta baru yang penting.

    Contoh format output (hanya poin-poin):
    - Pengguna resep ngopi di Kopi Janji Jiwa.
    - Pengguna rek ujian isukan.
    - Ngaran panggilan pengguna 'Ujang'.

    Percakapan:
    {history_str}
    """

    try:
        extraction_response = await gemini_model.generate_content_async(
            extraction_prompt)
        extracted_text = extraction_response.text.strip()
        logger.info(
            f"Ekstraksi memori untuk {chat_id}: {extracted_text[:100]}...")

        if extracted_text and extracted_text != "TIDAK_ADA_BARU":
            new_memories = []
            for line in extracted_text.split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    content = line[2:].strip()
                    is_duplicate = False
                    for existing_memory in data['memories']:
                        if content.lower() == existing_memory['content'].lower(
                        ):
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        new_memories.append({
                            "type": "fact",
                            "content": content,
                            "timestamp": int(time.time())
                        })

            if new_memories:
                data['memories'].extend(new_memories)
                logger.info(
                    f"Menambahkan {len(new_memories)} memori baru untuk {chat_id}."
                )
                save_user_data(chat_id)

    except Exception as e:
        logger.error(f"Error saat ekstraksi memori untuk {chat_id}: {e}",
                     exc_info=True)


async def start_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.message.chat_id

    user_data[chat_id] = {
        'session': None,
        'memory': [],
        'memories': [],
        'mood': DEFAULT_MOOD,
        'interaction_count': 0,
        'last_interaction_time': time.time()
    }
    save_user_data(chat_id)

    await update.message.reply_html(
        rf"Wih, {user.mention_html()}! Kumaha damang? Sini, uy, gabung. Aing Pangedulan AI ✨. Hayu urang ngobrol naon wae! 🤙",
    )
    logger.info(
        f"Pengguna {user.first_name} ({user.id}) memulai bot dengan perintah /start."
    )


async def infobot_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    current_mood = user_data.get(chat_id, {}).get('mood', DEFAULT_MOOD)

    info_text = (
        "Euy, jadi kieu, mang! Aing Pangedulan AI! ✨\n"
        "Otak aing make Google Gemini (model **gemini-2.5-flash-preview-05-20**).\n\n"
        f"Mood aing ayeuna lagi **{current_mood.upper()}** yeuh. Unggal urang ngobrol, mood aing bisa robah-robah!\n\n"
        "Aing bisa inget obrolan urang (memory system), jadi nyambung terus siga babaturan nongkrong. Aing siap ngobrolkeun **sagala rupa topik**!.\n\n"
        "**Paréntah:**\n"
        "🔹 /start - Keur ngobrol ti awal, sesi chat bakal direset.\n"
        "🔹 /infobot - Info ngeunaan aing.\n\n"
        "Hayu, urang lanjut ngobrol! 🚀")
    await update.message.reply_text(info_text, parse_mode='Markdown')


async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    chat_id = update.message.chat_id

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if chat_id not in user_data:
        loaded_data = load_user_data(chat_id)
        if loaded_data:
            user_data[chat_id] = loaded_data
            user_data[chat_id]['session'] = None
            logger.info(f"Memuat kembali data untuk {chat_id} dari Replit DB.")
        else:
            await start_command(update, context)
            return

    data = user_data[chat_id]
    current_mood = data['mood']

    mood_changed = update_mood(chat_id)
    if mood_changed:
        current_mood = data['mood']
        logger.info(
            f"Mereset sesi chat untuk {chat_id} karena mood berubah menjadi {current_mood}."
        )
        data['session'] = None

        await update.message.reply_text(
            f"Euy, mang! Mood aing ayeuna lagi **{current_mood.upper()}** yeuh. Jadi, gaya ngobrol aing bakal beda ti biasana. Gaskeun deui!",
            parse_mode='Markdown')
        time.sleep(0.5)
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        if data['session'] is None:
            logger.info(
                f"Menginisialisasi sesi chat baru untuk {chat_id} dengan mood {current_mood}."
            )

            initial_history_parts = [get_pangedulan_persona(current_mood)]

            if data['memories']:
                memories_list = "\n".join(
                    [f"- {m['content']}" for m in data['memories']])
                initial_history_parts.append(
                    f"Pangedulan AI, inget ieu ngeunaan pengguna: \n{memories_list}\n"
                    "Paké ingetan ieu sacara alami dina obrolan sia.")

            initial_history = [
                {
                    'role': 'user',
                    'parts': initial_history_parts
                },
                {
                    'role':
                    'model',
                    'parts': [
                        "Wih, anjay, si bos sumping! Sini, uy, geser ka dieu. Geus mesen ngopi can? Aing ti tadi gabut pisan. Enaknya kumaha yeuh urang?"
                    ]
                },
            ]

            data['session'] = gemini_model.start_chat(history=initial_history +
                                                      data['memory'])

        data['memory'].append({'role': 'user', 'parts': [user_text]})

        response = await data['session'].send_message_async(user_text)

        gemini_reply = response.text if response and response.text else "Waduh, uy, otak aing nge-freeze sakeudeung. 😅 Coba tanyakeun deui atuh."

        data['memory'].append({'role': 'model', 'parts': [gemini_reply]})

        if len(data['memory']) % MEMORY_EXTRACTION_THRESHOLD == 0:
            await extract_and_store_memories(chat_id, data['memory'])

    except Exception as e:
        logger.error(
            f"Error pada Gemini API (sesi {chat_id}, mood {current_mood}): {e}",
            exc_info=True)
        gemini_reply = "Aduh, uy! Koneksi ka pusat lagi error. 🧠⚡ Coba deui sakeudeung nya."

    data['last_interaction_time'] = time.time()
    save_user_data(chat_id)
    await update.message.reply_text(gemini_reply)


async def handle_sticker(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    sticker = update.message.sticker
    chat_id = update.message.chat_id

    logger.info(
        f"Menerima stiker dari {update.effective_user.first_name} ({chat_id}): Emoji={sticker.emoji}, Set={sticker.set_name}"
    )

    response_text = ""
    if sticker.emoji == "👍":
        response_text = "Enya, mantap! Satuju pisan aing! 👍"
    elif sticker.emoji == "😂":
        response_text = "Hahaha, sia mah bisa wae, uy! Pikaseurieun pisan! 😂"
    elif sticker.emoji == "🙏":
        response_text = "Siap, santuy weh! 🙏"
    elif sticker.emoji == "❤️":
        response_text = "Asiiiik, sia emang nu pang hadéna! ❤️"
    elif sticker.emoji == "🤙":
        response_text = "Gaskeun! 🤙"
    else:
        response_text = f"Wih, stikerna {sticker.emoji}! Kece, uy. Kumaha damang yeuh?"

    await update.message.reply_text(response_text)


async def error_handler(update: object,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Terjadi exception saat menangani update: {context.error}",
                 exc_info=context.error)


def main() -> None:
    if not TELEGRAM_TOKEN:
        logger.error("FATAL: TELEGRAM_TOKEN tidak ditemukan.")
        exit(1)

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("infobot", infobot_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Sticker, handle_sticker))

    logger.info(
        "Bot Telegram 'Pangedulan AI' dengan Evolusi Kepribadian siap menerima pesan..."
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()