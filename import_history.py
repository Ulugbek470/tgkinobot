import asyncio
import logging
import os
import re
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

import database as db

# Loglarni professional darajada sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID_ENV = os.getenv("CHANNEL_ID")
ADMIN_ID_ENV = os.getenv("ADMIN_ID") or os.getenv("SUPER_ADMIN_ID")

if not BOT_TOKEN or not CHANNEL_ID_ENV or not ADMIN_ID_ENV:
    raise ValueError("❌ .env faylida BOT_TOKEN, CHANNEL_ID va ADMIN_ID ko'rsatilgan bo'lishi kerak!")

CHANNEL_ID = int(CHANNEL_ID_ENV)
ADMIN_ID = int(ADMIN_ID_ENV)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==================== YORDAMCHI FUNKSIYALAR ====================

def parse_movie_data(text: str):
    """Matndan kino kodi va sifatini har qanday emojilar va formatlardan ajratib oladi."""
    if not text:
        return None, None

    clean_text = text.replace('\n', ' ')

    # 1. Sifatni aniqlash
    quality_match = re.search(r'(1080|720|480|360)\s*p?', clean_text, re.IGNORECASE)
    quality = quality_match.group(1) if quality_match else "720"

    # 2. Kodni aniqlash
    code_match = re.search(r'(?:kino\s*kodi|kodi|kod|code)\s*[:=\-]?\s*#?\s*(\d+)', clean_text, re.IGNORECASE)

    if not code_match:
        code_match = re.search(r'#(\d+)\b', clean_text)

    if not code_match:
        all_numbers = re.findall(r'\b\d{3,5}\b', clean_text)
        for num in all_numbers:
            if num not in ["1080", "720", "480", "360"]:
                return num, quality

    if code_match:
        return code_match.group(1), quality

    return None, quality


# ==================== 1. ESKI XABARLARNI SKAN QILISH ====================

async def scan_channel_history():
    """Kanalning tarixiy postlarini skan qiladi va bazaga saqlaydi."""
    logger.info("🚀 Kanal tarixini skan qilish boshlandi...")

    try:
        chat = await bot.get_chat(chat_id=CHANNEL_ID)
        logger.info(f"📡 Kanal topildi: {chat.title} (ID: {CHANNEL_ID})")
    except Exception as e:
        logger.error(f"❌ Xatolik: Kanal topilmadi yoki bot kanalda admin emas! ({e})")
        return

    count = 0
    max_check_id = 50000        # Maksimal post ID sohasi
    consecutive_errors = 0     # Ketma-ket bo'sh/xato chiqqan xabarlar sanagichi
    MAX_ERRORS = 300           # Ketma-ket 300 ta xabar topilmasa skan to'xtatiladi

    for msg_id in range(1, max_check_id):
        try:
            forwarded_msg = await bot.forward_message(
                chat_id=ADMIN_ID,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id
            )

            text = forwarded_msg.caption or forwarded_msg.text or ""

            try:
                await bot.delete_message(chat_id=ADMIN_ID, message_id=forwarded_msg.message_id)
            except Exception:
                pass

            if not text:
                consecutive_errors += 1
                continue

            movie_code, quality = parse_movie_data(text)

            if movie_code:
                saved = await db.save_movie_quality(
                    code=movie_code,
                    quality=quality,
                    message_id=msg_id,
                    caption=text
                )

                if saved:
                    count += 1
                    logger.info(f"✅ Saqlandi: Kod - #{movie_code} | Sifat - {quality}p | Post ID - {msg_id}")

            consecutive_errors = 0

        except TelegramRetryAfter as e:
            logger.warning(f"⚠️ Telegram limiti! {e.retry_after} soniya kutilmoqda...")
            await asyncio.sleep(e.retry_after)
            continue

        except (TelegramBadRequest, TelegramForbiddenError):
            consecutive_errors += 1
            if consecutive_errors >= MAX_ERRORS:
                logger.info(f"⚠️ Ketma-ket {consecutive_errors} ta xabar topilmadi. Skan yakunlandi.")
                break
            continue

        except Exception as e:
            logger.error(f"Kutilmagan xatolik (ID: {msg_id}): {e}")
            consecutive_errors += 1
            if consecutive_errors >= MAX_ERRORS:
                break
            continue

        await asyncio.sleep(0.15)

    logger.info(f"🎉 Skan yakunlandi! Jami {count} ta kino ma'lumoti bazaga kiritildi.")


# ==================== 2. REAL-TIME YANGI VA TAHRIRLANGAN POSTLARNI KUZATISH (24/7) ====================

@dp.channel_post(F.chat.id == CHANNEL_ID)
@dp.edited_channel_post(F.chat.id == CHANNEL_ID)
async def auto_sync_movie_post(message: Message):
    """
    Kanalga yangi post qo'shilganda YOKI mavjud post tahrirlanganda 
    bazadagi ma'lumotlarni real-time rejimda yangilaydi.
    """
    text = message.caption or message.text or ""

    movie_code, quality = parse_movie_data(text)

    if movie_code:
        saved = await db.save_movie_quality(
            code=movie_code,
            quality=quality,
            message_id=message.message_id,
            caption=text
        )

        if saved:
            logger.info(f"⚡ REAL-TIME: Post yangilandi/saqlandi | Kod: #{movie_code} | Sifat: {quality}p | Post ID: {message.message_id}")


# ==================== MAIN RUNNER ====================

async def main():
    await db.init_db()

    # 1. Eski xabarlarni tarix bo'yicha bir marta to'liq skan qiladi
    await scan_channel_history()

    # 2. Skan tugagach, Render'da 24/7 real-time yangilanishlar rejimiga o'tadi
    logger.info("📡 Real-time kuzatuv rejimi aktivlashtirildi. Uzluksiz ishlamoqda...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=["channel_post", "edited_channel_post"])
        except Exception as e:
            logger.error(f"⚠️ Polling jarayonida xatolik yuz berdi: {e}. 5 soniyadan so'ng qayta ulanadi...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Xizmat to'xtatildi.")
