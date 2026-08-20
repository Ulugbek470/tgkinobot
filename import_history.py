import asyncio
import logging
import os
import re
from dotenv import load_dotenv
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

import database as db

# Loglarni sozlash
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID")) if os.getenv("CHANNEL_ID") else None

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError(".env faylida BOT_TOKEN va CHANNEL_ID to'g'ri ko'rsatilgan bo'lishi kerak!")

bot = Bot(token=BOT_TOKEN)


async def scan_channel_history():
    await db.init_db()
    print("🚀 Kanal tarixi skan qilinmoqda...")

    try:
        chat = await bot.get_chat(chat_id=CHANNEL_ID)
        print(f"📡 Kanal topildi: {chat.title}")
    except Exception as e:
        print(f"❌ Xatolik: Kanal topilmadi yoki bot kanalda admin emas! ({e})")
        await bot.session.close()
        return

    count = 0
    max_check_id = 1000  # Skan qilinadigan oxirgi xabar ID chegarasi
    consecutive_errors = 0  # Ketma-ket topilmagan/o'chirilgan xabarlar soni

    try:
        for msg_id in range(1, max_check_id):
            try:
                # Xabarni to'g'ridan-to'g'ri forward qilib tekshiramiz
                msg = await bot.forward_message(
                    chat_id=CHANNEL_ID,
                    from_chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
                text = msg.caption or msg.text or ""

                # Vaqtinchalik forward xabarni o'chiramiz
                await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg.message_id)

                # 1. Sifatni aniqlash (360, 480, 720, 1080)
                quality_match = re.search(r'#(1080p|720p|480p|360p|1080|720|480|360)\b', text, re.IGNORECASE)

                # 2. Kino kodini aniqlash
                code_match = re.search(r'(?:kino\s*kodi|kodi|kod|code)\s*[:=\-]?\s*#?(\d+)', text, re.IGNORECASE)

                # Maxsus kalit so'z bo'lmasa, oddiy #123 tegini qidiramiz
                if not code_match:
                    code_match = re.search(r'#(\d+)\b', text)

                if code_match:
                    movie_code = code_match.group(1)
                    quality = quality_match.group(1).lower().replace("p", "") if quality_match else "720"

                    saved = await db.save_movie_quality(
                        code=movie_code,
                        quality=quality,
                        message_id=msg_id,
                        caption=text
                    )
                    if saved:
                        count += 1
                        print(f"✅ Saqlandi: Kod - #{movie_code}, Sifat - {quality}p, Post ID - {msg_id}")

                consecutive_errors = 0  # Muvaffaqiyatli xabarda xatoliklar sanagichini nolga tushiramiz

            except TelegramRetryAfter as e:
                # Telegram API limitga tushganda belgilangan vaqt kutadi
                logger.warning(f"⚠️ Telegram limiti! {e.retry_after} soniya kutilmoqda...")
                await asyncio.sleep(e.retry_after)
                continue

            except TelegramBadRequest:
                # Xabar o'chirilgan yoki mavjud bo'lmagan holat
                consecutive_errors += 1
                if consecutive_errors >= 50:
                    print(f"\n⚠️ Ketma-ket {consecutive_errors} ta xabar topilmadi. Skan to'xtatildi.")
                    break
                continue

            except Exception as e:
                logger.error(f"Kutilmagan xatolik (ID: {msg_id}): {e}")
                consecutive_errors += 1
                if consecutive_errors >= 50:
                    break
                continue

            # API so'rovlari oralig'idagi xavfsiz pauza
            await asyncio.sleep(0.1)

    finally:
        print(f"\n🎉 Skan yakunlandi! Jami {count} ta kino ma'lumoti bazaga kiritildi.")
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(scan_channel_history())
