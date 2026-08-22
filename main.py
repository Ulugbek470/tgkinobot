import asyncio
import logging
import os
import re
import html
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
    CallbackQuery
)

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_ENV = os.getenv("ADMIN_ID") or os.getenv("SUPER_ADMIN_ID")
CHANNEL_ID_ENV = os.getenv("CHANNEL_ID")

if not BOT_TOKEN or not ADMIN_ID_ENV or not CHANNEL_ID_ENV:
    raise ValueError("❌ .env faylida BOT_TOKEN, ADMIN_ID va CHANNEL_ID sozlanmagan!")

SUPER_ADMIN_ID = int(ADMIN_ID_ENV)
CHANNEL_ID = int(CHANNEL_ID_ENV)

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
    waiting_for_new_admin_id = State()
    waiting_for_del_admin_id = State()


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
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


async def get_admin_main_keyboard(is_super_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📢 Kanal qo'shish", callback_data="admin_add_chan"),
            InlineKeyboardButton(text="❌ Kanal o'chirish", callback_data="admin_del_chan")
        ],
        [
            InlineKeyboardButton(text="📊 Mukammal statistika", callback_data="admin_stats")
        ]
    ]
    
    if is_super_admin:
        buttons.append([
            InlineKeyboardButton(text="👤 Admin qo'shish", callback_data="admin_add_admin"),
            InlineKeyboardButton(text="🗑 Adminni o'chirish", callback_data="admin_del_admin")
        ])
        buttons.append([
            InlineKeyboardButton(text="📜 Adminlar ro'yxati", callback_data="admin_list")
        ])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def parse_movie_data(text: str):
    """Matndan kino kodi va sifatini har qanday emojilar va formatlardan ajratib oladi."""
    if not text:
        return None, None

    clean_text = text.replace('\n', ' ')

    quality_match = re.search(r'(1080|720|480|360)\s*p?', clean_text, re.IGNORECASE)
    quality = quality_match.group(1) if quality_match else "720"

    code_match = re.search(r'(?:kino\s*kodi|kodi|kod|code)\s*[:=\-]?\s*#?\s*(\d+)', clean_text, re.IGNORECASE)

    if not code_match:
        code_match = re.search(r'#(\d+)', clean_text)

    if not code_match:
        all_numbers = re.findall(r'\b\d{3,5}\b', clean_text)
        for num in all_numbers:
            if num not in ["1080", "720", "480", "360"]:
                return num, quality

    if code_match:
        return code_match.group(1), quality

    return None, quality


# ==================== AVTOMATIK KINO QO'SHISH ====================

@dp.channel_post(F.chat.id == CHANNEL_ID)
@dp.edited_channel_post(F.chat.id == CHANNEL_ID)
async def auto_save_movie_from_channel(message: Message):
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
            logger.info(f"✅ Avto-saqlandi: Kod - #{movie_code} | Sifat - {quality}p | Post ID - {message.message_id}")


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
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
            reply_markup=await get_sub_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    await message.answer(
        f"Assalomu alaykum, <b>{html.escape(message.from_user.first_name)}</b>!\n\n"
        f"🎬 <i>Kino kodini yuboring (Masalan: 700 yoki 1111):</i>",
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.delete()
        await call.message.answer("✅ Rahmat! Barcha kanallarga obuna bo'ldingiz.\n\n🎬 Endi kino kodini yuborishingiz mumkin.")
    else:
        await call.answer("❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)


# ==================== ADMIN PANEL & ADMINLARNI BOSHQARISH ====================

@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    if not await is_admin(user_id):
        return

    users_count, movies_count, banned_count = await db.get_extended_stats()
    text = (
        "🛠 <b>Admin Boshqaruv Paneli</b>\n\n"
        f"👥 <b>Foydalanuvchilar:</b> <code>{users_count}</code>\n"
        f"🎬 <b>Kinolar soni:</b> <code>{movies_count}</code>\n"
        f"🚫 <b>Bloklanganlar:</b> <code>{banned_count}</code>\n"
    )
    
    is_super = (user_id == SUPER_ADMIN_ID)
    await message.answer(
        text, 
        reply_markup=await get_admin_main_keyboard(is_super_admin=is_super), 
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(F.data == "admin_add_admin")
async def add_admin_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Bu bo'lim faqat asosiy admin uchun!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_new_admin_id)
    await call.message.answer("📥 Yangi adminning Telegram ID raqamini kiriting:")
    await call.answer()


@dp.message(AdminStates.waiting_for_new_admin_id)
async def process_add_admin(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Telegram ID faqat raqamlardan iborat bo'lishi kerak. Qayta kiriting:")
        return

    new_admin_id = int(text)
    await db.add_admin_user(new_admin_id)
    await state.clear()
    await message.answer(f"✅ User ID: <code>{new_admin_id}</code> admin sifatida muvaffaqiyatli qo'shildi!", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "admin_del_admin")
async def del_admin_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Bu bo'lim faqat asosiy admin uchun!", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_del_admin_id)
    await call.message.answer("🗑 O'chirmoqchi bo'lgan adminning Telegram ID raqamini kiriting:")
    await call.answer()


@dp.message(AdminStates.waiting_for_del_admin_id)
async def process_del_admin(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Telegram ID faqat raqamlardan iborat bo'lishi kerak. Qayta kiriting:")
        return

    del_id = int(text)
    if del_id == SUPER_ADMIN_ID:
        await message.answer("❌ Asosiy adminni o'chirib bo'lmaydi!")
        await state.clear()
        return

    await db.remove_admin_user(del_id)
    await state.clear()
    await message.answer(f"✅ Admin ID: <code>{del_id}</code> muvaffaqiyatli o'chirildi!", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "admin_list")
async def show_admins_list(call: CallbackQuery):
    if call.from_user.id != SUPER_ADMIN_ID:
        await call.answer("❌ Bu bo'lim faqat asosiy admin uchun!", show_alert=True)
        return

    admins = await db.get_admin_list()
    text = "📜 <b>Bot Adminlari Ro'yxati:</b>\n\n"
    text += f"👑 <b>Asosiy Admin (SUPER):</b> <code>{SUPER_ADMIN_ID}</code>\n"

    other_admins = [adm for adm in admins if adm != SUPER_ADMIN_ID]
    if other_admins:
        text += "\n👤 <b>Yordamchi Adminlar:</b>\n"
        for adm in other_admins:
            text += f"🔹 <code>{adm}</code>\n"
    else:
        text += "\n<i>(Hozircha yordamchi adminlar mavjud emas)</i>"

    await call.message.answer(text, parse_mode=ParseMode.HTML)
    await call.answer()


# ==================== ADMIN: KANAL BOSHQRUVI ====================

@dp.callback_query(F.data == "admin_add_chan")
async def add_channel_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_channel_id)
    await call.message.answer("📥 Kanal ID'sini kiriting (Masalan: `-100123456789`):")
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
    await message.answer(f"✅ <b>{html.escape(title)}</b> kanali majburiy obuna ro'yxatiga qo'shildi!", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "admin_del_chan")
async def delete_channel_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return

    channels = await db.get_active_channels()
    if not channels:
        await call.message.answer("⚠️ Hech qanday majburiy kanal topilmadi.")
        await call.answer()
        return

    text = "🗑 <b>O'chirmoqchi bo'lgan kanal ID'sini kiriting:</b>\n\n"
    for ch in channels:
        text += f"🔹 {html.escape(ch['title'])} - <code>{ch['channel_id']}</code>\n"

    await state.set_state(AdminStates.waiting_for_channel_delete)
    await call.message.answer(text, parse_mode=ParseMode.HTML)
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
            "⚠️ <b>Botdan foydalanish uchun majburiy kanallarga obuna bo'ling:</b>",
            reply_markup=await get_sub_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    code = message.text.strip().replace("#", "")
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

    raw_caption = movie.get("caption")
    if raw_caption:
        # Xatolik bermasligi uchun HTML maxsus belgilarni tozalaymiz
        caption_text = html.escape(raw_caption)
    else:
        caption_text = f"🎬 <b>Kino kodi:</b> <code>#{code}</code>"

    try:
        await message.answer(
            caption_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Xabar yuborishda HTML xatosi, oddiy matn rejimiga o'tilmoqda: {e}")
        # Agar matnda kutilmagan format xatosi bo'lsa, parse_mode'siz yuboriladi
        await message.answer(
            raw_caption or f"🎬 Kino kodi: #{code}",
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

    try:
        await bot.copy_message(
            chat_id=call.from_user.id,
            from_chat_id=CHANNEL_ID,
            message_id=msg_id
        )
        await call.answer()
    except Exception as e:
        logger.error(f"Kino yuborishda xatolik: {e}")
        await call.answer("❌ Xatolik: Video kanal topilmadi yoki o'chirilgan.", show_alert=True)


# ==================== ISHGA TUSHIRISH ====================

async def main():
    await db.init_db()
    if SUPER_ADMIN_ID:
        await db.add_admin_user(SUPER_ADMIN_ID)

    logger.info("🚀 Professional Kino Boti muvaffaqiyatli ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
