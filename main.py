import asyncio
import logging
import os
from typing import Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from dotenv import load_dotenv

import database as db

# Environment o'zgaruvchilarini yuklash
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

if not BOT_TOKEN:
    raise ValueError(".env faylida BOT_TOKEN ko'rsatilmagan!")

# Logging sozlamalari
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# FSM State'lar (Formlar)
class AdminStates(StatesGroup):
    waiting_for_movie = State()
    waiting_for_channel = State()
    waiting_for_broadcast = State()


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def check_subscription(user_id: int) -> bool:
    """Foydalanuvchi majburiy obuna kanallariga a'zo ekanligini tekshiradi."""
    channels = await db.get_active_channels()
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Kanal obunasini tekshirishda xatolik ({ch['channel_id']}): {e}")
            continue
    return True


async def get_sub_keyboard() -> InlineKeyboardMarkup:
    """Obuna bo'lish tugmalarini shakllantiradi."""
    channels = await db.get_active_channels()
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=ch["title"], url=ch["link"])])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== HANDLERLAR ====================

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    
    # Ban holatini tekshirish
    if await db.is_user_banned(user_id):
        await message.answer("❌ Siz botdan foydalanishdan bloklangansiz.")
        return

    # Foydalanuvchini bazaga qo'shish
    await db.add_user(
        user_id=user_id,
        full_name=message.from_user.full_name,
        username=message.from_user.username
    )

    # Obunani tekshirish
    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=await get_sub_keyboard()
        )
        return

    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\n\n"
        f"🎬 Kino kodini yuboring:"
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ Rahmat! Endi kino kodini yuborishingiz mumkin.")
    else:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


# ==================== KINO IZLASH ====================

@dp.message(F.text & ~F.text.startswith("/"))
async def get_movie_handler(message: Message):
    user_id = message.from_user.id

    if await db.is_user_banned(user_id):
        return

    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ Botdan foydalanish uchun kanallarga obuna bo'ling:",
            reply_markup=await get_sub_keyboard()
        )
        return

    code = message.text.strip()
    movie = await db.get_movie(code)

    if not movie:
        await message.answer("❌ Bunday kodli kino topilmadi.")
        return

    # Sifat tugmalarini yaratish
    buttons = []
    qualities = [("360p", "msg_360"), ("480p", "msg_480"), ("720p", "msg_720"), ("1080p", "msg_1080")]
    
    row = []
    for label, key in qualities:
        if movie.get(key):
            row.append(InlineKeyboardButton(text=label, callback_data=f"get_m:{code}:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    caption_text = movie.get("caption") or f"🎬 Kino kodi: #{code}"
    
    await message.answer(
        caption_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    )


@dp.callback_query(F.data.startswith("get_m:"))
async def send_movie_quality(call: CallbackQuery):
    _, code, quality_key = call.data.split(":")
    movie = await db.get_movie(code)

    if not movie or not movie.get(quality_key):
        await call.answer("❌ Videoni yuborishda xatolik yuz berdi.", show_alert=True)
        return

    msg_id = movie[quality_key]
    channel_id = os.getenv("CHANNEL_ID")

    try:
        await bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=channel_id,
            message_id=msg_id
        )
        await call.answer()
    except Exception as e:
        logger.error(f"Kino yuborishda xatolik: {e}")
        await call.answer("❌ Xatolik: Video topilmadi yoki o'chirilgan.", show_alert=True)


# ==================== ADMIN PANEL ====================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    user_id = message.from_user.id
    admins = await db.get_admin_list()

    if ADMIN_ID and user_id != ADMIN_ID and user_id not in admins:
        return

    users_count, movies_count, banned_count = await db.get_extended_stats()

    text = (
        "🛠 **Admin Paneli**\n\n"
        f"👥 Foydalanuvchilar: `{users_count}`\n"
        f"🎬 Kinolar soni: `{movies_count}`\n"
        f"🚫 Bloklanganlar: `{banned_count}`"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanal qo'shish", callback_data="add_chan")],
        [InlineKeyboardButton(text="✉️ Xabar yuborish (Broadcast)", callback_data="broadcast")]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")


# ==================== ISHGA TUSHIRISH ====================

async def main():
    # Ma'lumotlar bazasini ishga tushirish
    await db.init_db()

    # Boshlang'ich adminni bazaga kiritish
    if ADMIN_ID:
        await db.add_admin_user(ADMIN_ID)

    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
