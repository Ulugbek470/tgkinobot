import asyncio
import logging
import os
import re
from dotenv import load_dotenv

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError

import database as db

# Loglarni sozlash
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
    raise ValueError("❌ .env faylida BOT_TOKEN, CHANNEL_ID va ADMIN_ID (yoki SUPER_ADMIN_ID) ko'rsatilgan bo'lishi kerak!")

CHANNEL_ID = int(CHANNEL_ID_ENV)
ADMIN_ID = int(ADMIN_ID_ENV)

bot = Bot(token=BOT_TOKEN)


async def scan_channel_history():
    """Kanal tarixini skan qilib, kinolarni bazaga saqlaydi."""
    await db.init_db()
    print("🚀 Kanal tarixini skan qilish boshlandi...")

    try:
        chat = await bot.get_chat(chat_id=CHANNEL_ID)
        print(f"📡 Kanal topildi: {chat.title} (ID: {CHANNEL_ID})")
    except Exception as e:
        print(f"❌ Xatolik: Kanal topilmadi yoki bot kanalda admin emas! ({e})")
        await bot.session.close()
        return

    count = 0
    max_check_id = 10000      # Skan qilinadigan maksimal post ID chegarasi
    consecutive_errors = 0    # Ketma-ket topilmagan/o'chirilgan xabarlar soni
    MAX_ERRORS = 50           # Ketma-ket 50 ta xabar topilmasa, skan to'xtatiladi

    try:
        for msg_id in range(1, max_check_id):
            try:
                # Kanaldagi xabarni admin chatiga forward qilamiz (to'liq Message obyekti qaytadi)
                forwarded_msg = await bot.forward_message(
                    chat_id=ADMIN_ID,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )

                text = forwarded_msg.caption or forwarded_msg.text or ""

                # Vaqtinchalik xabarni admin chatidan o'chiramiz
                try:
                    await bot.delete_message(chat_id=ADMIN_ID, message_id=forwarded_msg.message_id)
                except Exception:
                    pass

                if not text:
                    consecutive_errors = 0
                    continue

                # 1. Sifatni aniqlash (1080p, 720p, 480p, 360p)
                quality_match = re.search(r'#(1080p|720p|480p|360p|1080|720|480|360)\b', text, re.IGNORECASE)

                # 2. Kino kodini aniqlash (Masalan: "Kino kodi: 123", "Kod: #123", "Code - 123")
                code_match = re.search(r'(?:kino\s*kodi|kodi|kod|code)\s*[:=\-]?\s*#?(\d+)', text, re.IGNORECASE)

                # Maxsus kalit so'z bo'lmasa, oddiy #123 tegini qidiramiz
                if not code_match:
                    code_match = re.search(r'#(\d+)\b', text)

                if code_match:
                    movie_code = code_match.group(1)
                    quality = quality_match.group(1).lower().replace("p", "") if quality_match else "720"

                    # Bazaga saqlash
                    saved = await db.save_movie_quality(
                        code=movie_code,
                        quality=quality,
                        message_id=msg_id,
                        caption=text
                    )

                    if saved:
                        count += 1
                        print(f"✅ Saqlandi: Kod - #{movie_code} | Sifat - {quality}p | Post ID - {msg_id}")

                consecutive_errors = 0  # Topilgan xabarda xatoliklar sanagichini nolga tushiramiz

            except TelegramRetryAfter as e:
                logger.warning(f"⚠️ Telegram limiti! {e.retry_after} soniya kutilmoqda...")
                await asyncio.sleep(e.retry_after)
                continue

            except (TelegramBadRequest, TelegramForbiddenError):
                consecutive_errors += 1
                if consecutive_errors >= MAX_ERRORS:
                    print(f"\n⚠️ Ketma-ket {consecutive_errors} ta xabar topilmadi. Skan yakunlandi.")
                    break
                continue

            except Exception as e:
                logger.error(f"Kutilmagan xatolik (ID: {msg_id}): {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_ERRORS:
                    break
                continue

            # Limitga tushmaslik uchun xavfsiz pauza
            await asyncio.sleep(0.15)

    finally:
        print(f"\n🎉 Skan yakunlandi! Jami {count} ta kino ma'lumoti bazaga kiritildi.")
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(scan_channel_history())
    except (KeyboardInterrupt, SystemExit):
        print("\nSkan jarayoni to'xtatildi.")
