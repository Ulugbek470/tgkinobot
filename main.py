import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Message, 
    CallbackQuery,
    ErrorEvent
)

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_ENV = os.getenv("ADMIN_ID") or os.getenv("SUPER_ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not ADMIN_ID_ENV:
    raise ValueError("❌ .env faylida BOT_TOKEN va ADMIN_ID sozlanmagan!")

ADMIN_ID = int(ADMIN_ID_ENV)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ==================== FSM STATES ====================

class AdminStates(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_title = State()
    waiting_for_channel_link = State()
    waiting_for_channel_delete = State()
    waiting_for_broadcast_message = State()
    waiting_for_user_ban = State()
    waiting_for_user_unban = State()


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    admins = await db.get_admin_list()
    return user_id in admins


async def check_subscription(user_id: int) -> bool:
    channels = await db.get_active_channels()
    for ch in channels:
        try:
            ch_id = int(ch["channel_id"]) if str(ch["channel_id"]).replace("-", "").isdigit() else ch["channel_id"]
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Kanal obunasini tekshirishda xatolik ({ch['channel_id']}): {e}")
            continue
    return True


async def get_sub_keyboard() -> InlineKeyboardMarkup:
    channels = await db.get_active_channels()
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch["link"])])
    buttons.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📢 Kanal qo'shish", callback_data="admin_add_chan"),
            InlineKeyboardButton(text="❌ Kanal o'chirish", callback_data="admin_del_chan")
        ],
        [
            InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="📊 Mukammal statistika", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton(text="🚫 Ban qilish", callback_data="admin_ban_user"),
            InlineKeyboardButton(text="✅ Bandan olish", callback_data="admin_unban_user")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== GENERAL HANDLERS ====================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if await db.is_user_banned(user_id):
        await message.answer("❌ Siz botdan foydalanishdan bloklangansiz.")
        return

    await db.add_user(
        user_id=user_id,
        full_name=message.from_user.full_name,
        username=message.from_user.username
    )

    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ **Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:**",
            reply_markup=await get_sub_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await message.answer(
        f"Assalomu alaykum, **{message.from_user.first_name}**!\n\n"
        f"🎬 *Kino kodini yuboring:*",
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ Rahmat! Barcha kanallarga obuna bo'ldingiz.\n\n🎬 Endi kino kodini yuborishingiz mumkin.")
    else:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


# ==================== ADMIN: KANAL QO'SHISH / O'CHIRISH ====================

@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    await state.clear()
    if not await is_admin(message.from_user.id):
        return

    users_count, movies_count, banned_count = await db.get_extended_stats()
    text = (
        "🛠 **Admin Boshqaruv Paneli**\n\n"
        f"👥 **Foydalanuvchilar:** `{users_count}`\n"
        f"🎬 **Kinolar soni:** `{movies_count}`\n"
        f"🚫 **Bloklanganlar:** `{banned_count}`\n"
    )
    await message.answer(text, reply_markup=await get_admin_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


@dp.callback_query(F.data == "admin_add_chan")
async def add_channel_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_channel_id)
    await call.message.answer("📥 Kanal ID'sini yoki username'ini kiriting (Masalan: `-100123456789`):")
    await call.answer()


@dp.message(AdminStates.waiting_for_channel_id)
async def process_channel_id(message: Message, state: FSMContext):
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AdminStates.waiting_for_channel_title)
    await message.answer("📝 Kanal nomini kiriting (Masalan: `Bosh Kanal`):")


@dp.message(AdminStates.waiting_for_channel_title)
async def process_channel_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.waiting_for_channel_link)
    await message.answer("🔗 Kanal havolasini (Link) kiriting (Masalan: `https://t.me/kanal`):")


@dp.message(AdminStates.waiting_for_channel_link)
async def process_channel_link(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data["channel_id"]
    title = data["title"]
    link = message.text.strip()

    await db.add_channel(channel_id=channel_id, title=title, link=link)
    await state.clear()
    await message.answer(f"✅ **{title}** kanali majburiy obuna ro'yxatiga qo'shildi!", parse_mode=ParseMode.MARKDOWN)


@dp.callback_query(F.data == "admin_del_chan")
async def delete_channel_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return

    channels = await db.get_active_channels()
    if not channels:
        await call.message.answer("⚠️ Hech qanday majburiy kanal topilmadi.")
        await call.answer()
        return

    text = "🗑 **O'chirmoqchi bo'lgan kanal ID'sini kiriting:**\n\n"
    for ch in channels:
        text += f"🔹 {ch['title']} - `{ch['channel_id']}`\n"

    await state.set_state(AdminStates.waiting_for_channel_delete)
    await call.message.answer(text, parse_mode=ParseMode.MARKDOWN)
    await call.answer()


@dp.message(AdminStates.waiting_for_channel_delete)
async def process_delete_channel(message: Message, state: FSMContext):
    channel_id = message.text.strip()
    await db.delete_channel(channel_id)
    await state.clear()
    await message.answer("✅ Kanal muvaffaqiyatli o'chirildi.")


# ==================== KINO IZLASH (ODDIY FOYDALANUVCHILAR UCHUN) ====================

@dp.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def get_movie_handler(message: Message):
    user_id = message.from_user.id

    if await db.is_user_banned(user_id):
        return

    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ **Botdan foydalanish uchun majburiy kanallarga obuna bo'ling:**",
            reply_markup=await get_sub_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    code = message.text.strip()
    movie = await db.get_movie(code)

    if not movie:
        await message.answer("❌ Bunday kodli kino topilmadi.")
        return

    qualities = [("360p", "msg_360"), ("480p", "msg_480"), ("720p", "msg_720"), ("1080p", "msg_1080")]
    buttons = []
    row = []

    for label, key in qualities:
        if movie.get(key):
            row.append(InlineKeyboardButton(text=f"🎥 {label}", callback_data=f"get_m:{code}:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    caption_text = movie.get("caption") or f"🎬 **Kino kodi:** `{code}`"

    await message.answer(
        caption_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
        parse_mode=ParseMode.MARKDOWN
    )


@dp.callback_query(F.data.startswith("get_m:"))
async def send_movie_quality(call: CallbackQuery):
    _, code, quality_key = call.data.split(":")
    movie = await db.get_movie(code)

    if not movie or not movie.get(quality_key):
        await call.answer("❌ Videoni yuborishda xatolik yuz berdi.", show_alert=True)
        return

    msg_id = movie[quality_key]

    try:
        await bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=int(CHANNEL_ID) if CHANNEL_ID.replace("-", "").isdigit() else CHANNEL_ID,
            message_id=msg_id
        )
        await call.answer()
    except Exception as e:
        logger.error(f"Kino yuborishda xatolik: {e}")
        await call.answer("❌ Xatolik: Video kanal topilmadi yoki o'chirilgan.", show_alert=True)


# ==================== ISHGA TUSHIRISH ====================

async def main():
    await db.init_db()
    if ADMIN_ID:
        await db.add_admin_user(ADMIN_ID)

    logger.info("🚀 Professional Kino Boti muvaffaqiyatli ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
