import asyncio
import logging
import os
import re
from dotenv import load_dotenv
from aiogram import Bot

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID")) if os.getenv("CHANNEL_ID") else None

if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError(".env faylida BOT_TOKEN va CHANNEL_ID to'g'ri ko'rsatilgan bo'lishi kerak!")

bot = Bot(token=BOT_TOKEN)


async def scan_channel_history():
    await db.init_db()
    logging.basicConfig(level=logging.INFO)
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
    consecutive_errors = 0  # Ketma-ket topilmagan xabarlar soni

    for msg_id in range(1, max_check_id):
        try:
            # Xabarni kanaldan o'ziga forward qilib matnni o'qiymiz
            msg = await bot.forward_message(
                chat_id=CHANNEL_ID,
                from_chat_id=CHANNEL_ID,
                message_id=msg_id
            )
            text = msg.caption or msg.text or ""
            
            # Forward qilingan vaqtinchalik xabarni o'chiramiz
            await bot.delete_message(chat_id=CHANNEL_ID, message_id=msg.message_id)

            # 1. 4 xil sifat formatini izlash (360, 480, 720, 1080)
            quality_match = re.search(r'#(1080p|720p|480p|360p|1080|720|480|360)\b', text, re.IGNORECASE)

            # 2. Kino kodi uchun har xil izlash ko'rinishlari
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

        except Exception:
            consecutive_errors += 1
            # Agar ketma-ket 50 ta xabar topilmasa, skan jarayonini to'xtatamiz
            if consecutive_errors >= 50:
                print(f"\n⚠️ Ketma-ket {consecutive_errors} ta xabar topilmadi. Skan to'xtatildi.")
                break
            continue

        await asyncio.sleep(0.05)  # Telegram API limitiga tushmaslik uchun pauza

    print(f"\n🎉 Skan yakunlandi! Jami {count} ta kino ma'lumoti bazaga kiritildi.")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(scan_channel_history())
