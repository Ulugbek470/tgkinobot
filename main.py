import re
import os
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, 
    CallbackQuery,
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID")) if os.getenv("CHANNEL_ID") else None
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID") or os.getenv("ADMIN_ID", 0))
API_URL = os.getenv("API_URL", "https://my-bot-db-service.onrender.com").rstrip('/')

if not BOT_TOKEN or not CHANNEL_ID or not SUPER_ADMIN_ID:
    raise ValueError(".env faylida BOT_TOKEN, CHANNEL_ID va SUPER_ADMIN_ID to'g'ri ko'rsatilgan bo'lishi kerak!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Global HTTP Session (so'rovlar tezligi uchun)
session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()
    return session


# ==================== WEB SERVICE (API) MITOQLARI ====================

class DatabaseAPI:
    @staticmethod
    async def _post(endpoint: str, json_data: dict) -> dict:
        sess = await get_session()
        try:
            async with sess.post(f"{API_URL}{endpoint}", json=json_data) as resp:
                if resp.status == 200:
                    return await resp.json()
                logging.error(f"API Post Error [{resp.status}]: {await resp.text()}")
                return {}
        except Exception as e:
            logging.error(f"HTTP Connection error: {e}")
            return {}

    @staticmethod
    async def _get(endpoint: str) -> dict:
        sess = await get_session()
        try:
            async with sess.get(f"{API_URL}{endpoint}") as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}
        except Exception as e:
            logging.error(f"HTTP Connection error: {e}")
            return {}

    async def add_user(self, user_id: int, full_name: str, username: Optional[str] = None):
        return await self._post("/users/add", {
            "user_id": user_id,
            "full_name": full_name,
            "username": username
        })

    async def is_user_banned(self, user_id: int) -> bool:
        res = await self._get(f"/users/{user_id}/banned")
        return res.get("is_banned", False)

    async def set_user_ban_status(self, user_id: int, is_banned: bool):
        return await self._post("/users/ban", {
            "user_id": user_id,
            "is_banned": is_banned
        })

    async def get_extended_stats(self) -> Tuple[int, int, int]:
        res = await self._get("/stats")
        return res.get("users_count", 0), res.get("movies_count", 0), res.get("banned_count", 0)

    async def get_all_active_user_ids(self) -> List[int]:
        res = await self._get("/users/active")
        return res.get("user_ids", [])

    async def add_admin_user(self, user_id: int):
        return await self._post("/admins/add", {"user_id": user_id})

    async def remove_admin_user(self, user_id: int):
        return await self._post("/admins/remove", {"user_id": user_id})

    async def get_admin_list(self) -> List[int]:
        res = await self._get("/admins/list")
        return res.get("admins", [])

    async def add_channel(self, channel_id: int, title: str, link: str):
        return await self._post("/channels/add", {
            "channel_id": channel_id,
            "title": title,
            "link": link
        })

    async def remove_channel(self, channel_id: int):
        return await self._post("/channels/remove", {"channel_id": channel_id})

    async def get_active_channels(self) -> List[Dict[str, Any]]:
        res = await self._get("/channels/list")
        return res.get("channels", [])

    async def save_movie_quality(self, code: str, quality: str, message_id: int, caption: str) -> bool:
        res = await self._post("/movies/save", {
            "code": str(code),
            "quality": quality,
            "message_id": message_id,
            "caption": caption
        })
        return res.get("success", False)

    async def get_movie(self, code: str) -> Optional[Dict[str, Any]]:
        res = await self._get(f"/movies/{code}")
        return res if res else None


db = DatabaseAPI()


# ==================== FSM HOLATLARI ====================

class AdminStates(StatesGroup):
    waiting_for_add_admin = State()
    waiting_for_remove_admin = State()
    waiting_for_ban_id = State()
    waiting_for_unban_id = State()
    waiting_for_channel_add = State()
    waiting_for_channel_remove = State()
    waiting_for_broadcast_msg = State()
    waiting_for_broadcast_btn_ask = State()
    waiting_for_broadcast_btn_details = State()


# ==================== KLAVIATURALAR ====================

def main_menu_keyboard():
    kb = [
        [KeyboardButton(text="🎬 Kino izlash")],
        [KeyboardButton(text="ℹ️ Bot haqida")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


async def check_subscription_keyboard():
    channels = await db.get_active_channels()
    inline_keyboard = []
    
    for ch in channels:
        inline_keyboard.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch['link'])])
        
    inline_keyboard.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def admin_panel_keyboard(user_id: int):
    is_super = (user_id == SUPER_ADMIN_ID)
    
    kb = [
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="📢 Kanallarni boshqarish", callback_data="admin_channels"),
            InlineKeyboardButton(text="🚫 Ban tizimi", callback_data="admin_ban_menu")
        ]
    ]
    
    if is_super:
        kb.append([InlineKeyboardButton(text="👑 Adminlarni boshqarish", callback_data="admin_manage_admins")])
        
    kb.append([InlineKeyboardButton(text="❌ Yopish", callback_data="admin_close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ==================== YORDAMCHI FUNKSIYALAR ====================

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    admins = await db.get_admin_list()
    return user_id in admins


async def is_user_subscribed(user_id: int) -> bool:
    channels = await db.get_active_channels()
    if not channels:
        return True
        
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch['channel_id'], user_id=user_id)
            if member.status not in ["creator", "administrator", "member"]:
                return False
        except Exception as e:
            logging.error(f"Obunani tekshirishda xatolik ({ch['channel_id']}): {e}")
            continue
    return True


# ==================== ADMIN DASHBOARD ====================

@dp.message(Command("admin"))
async def admin_dashboard(message: Message, state: FSMContext):
    await state.clear()
    if not await is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 <b>Professional Admin Boshqaruv Paneli</b>\n\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(message.from_user.id)
    )


@dp.callback_query(F.data == "admin_stats")
async def show_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    users_count, movies_count, banned_count = await db.get_extended_stats()
    await callback.message.edit_text(
        f"📊 <b>Bot Statistikasi:</b>\n\n"
        f"👤 Jami foydalanuvchilar: <b>{users_count}</b> ta\n"
        f"🎬 Bazadagi kinolar: <b>{movies_count}</b> ta\n"
        f"🚫 Bloklanganlar: <b>{banned_count}</b> ta",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(callback.from_user.id)
    )


@dp.callback_query(F.data == "admin_close")
async def close_admin_panel(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.delete()


@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("❌ Amaliyot bekor qilindi.", reply_markup=main_menu_keyboard())


# ==================== ADMINLARNI BOSHQARISH ====================

@dp.callback_query(F.data == "admin_manage_admins")
async def manage_admins_menu(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        await callback.answer("❌ Bu bo'lim faqat Asosiy Admin uchun!", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Adminni o'chirish", callback_data="remove_admin")],
        [InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="list_admins")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back_main")]
    ])
    await callback.message.edit_text("👑 <b>Adminlarni Boshqarish Bo'limi</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "admin_back_main")
async def back_to_main_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(
        "🛠 <b>Professional Admin Boshqaruv Paneli</b>",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(callback.from_user.id)
    )


@dp.callback_query(F.data == "add_admin")
async def start_add_admin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_for_add_admin)
    await callback.message.edit_text("➕ Yangi adminning <b>Telegram ID</b>sini yuboring:\n\nBekor qilish: /cancel", parse_mode="HTML")


@dp.message(AdminStates.waiting_for_add_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Noto'g'ri me'zon! Telegram ID faqat raqamlardan iborat bo'lishi kerak.")
        return

    new_admin_id = int(message.text)
    await db.add_admin_user(new_admin_id)
    await state.clear()
    await message.answer(f"✅ <code>{new_admin_id}</code> muvaffaqiyatli admin etib tayinlandi!", parse_mode="HTML")


@dp.callback_query(F.data == "remove_admin")
async def start_remove_admin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    await state.set_state(AdminStates.waiting_for_remove_admin)
    await callback.message.edit_text("➖ O'chiriladigan adminning <b>Telegram ID</b>sini yuboring:\n\nBekor qilish: /cancel", parse_mode="HTML")


@dp.message(AdminStates.waiting_for_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Noto'g'ri ID kiritildi.")
        return

    target_id = int(message.text)
    if target_id == SUPER_ADMIN_ID:
        await message.answer("⚠️ Asosiy adminni tizimdan o'chirib bo'lmaydi!")
        return

    await db.remove_admin_user(target_id)
    await state.clear()
    await message.answer(f"✅ <code>{target_id}</code> adminlikdan olib tashlandi.", parse_mode="HTML")


@dp.callback_query(F.data == "list_admins")
async def list_admins_handler(callback: CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID:
        return
    admins = await db.get_admin_list()
    admin_str = "\n".join([f"• <code>{a}</code>" for a in admins])
    await callback.message.edit_text(f"📋 <b>Mavjud Adminlar Ro'yxati:</b>\n\n👑 SuperAdmin: <code>{SUPER_ADMIN_ID}</code>\n{admin_str}", parse_mode="HTML")


# ==================== MAJBURIY OBUNA KANALLARI ====================

@dp.callback_query(F.data == "admin_channels")
async def manage_channels_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")],
        [InlineKeyboardButton(text="➖ Kanalni o'chirish", callback_data="remove_channel")],
        [InlineKeyboardButton(text="📜 Kanallar ro'yxati", callback_data="list_channels")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back_main")]
    ])
    await callback.message.edit_text("📢 <b>Majburiy Obuna Kanallarini Boshqarish</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "add_channel")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_channel_add)
    await callback.message.edit_text(
        "➕ Kanal ma'lumotlarini quyidagi formatda yuboring:\n\n"
        "<code>Kanal_ID | Kanal_Nomi | Kanal_Link</code>\n\n"
        "<b>Masalan:</b>\n<code>-100123456789 | Bosh Kanal | https://t.me/kanal_link</code>\n\n"
        "<i>Eslatma: Bot ushbu kanalda admin bo'lishi shart!</i>",
        parse_mode="HTML"
    )


@dp.message(AdminStates.waiting_for_channel_add)
async def process_add_channel(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        ch_id, title, link = map(str.strip, message.text.split("|"))
        await db.add_channel(channel_id=int(ch_id), title=title, link=link)
        await state.clear()
        await message.answer(f"✅ <b>{title}</b> kanali muvaffaqiyatli qo'shildi!", parse_mode="HTML")
    except Exception:
        await message.answer("⚠️ Noto'g'ri format kiritildi! Iltimos, namunaga qarab qayta yuboring.")


@dp.callback_query(F.data == "remove_channel")
async def start_remove_channel(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_channel_remove)
    await callback.message.edit_text("➖ O'chirmoqchi bo'lgan kanalingizning **Kanal ID**sini yuboring:", parse_mode="HTML")


@dp.message(AdminStates.waiting_for_channel_remove)
async def process_remove_channel(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        ch_id = int(message.text.strip())
        await db.remove_channel(channel_id=ch_id)
        await state.clear()
        await message.answer("✅ Kanal majburiy obuna ro'yxatidan olib tashlandi.")
    except Exception:
        await message.answer("⚠️ Noto'g'ri Kanal ID kiritildi.")


@dp.callback_query(F.data == "list_channels")
async def list_channels_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    channels = await db.get_active_channels()
    if not channels:
        await callback.message.edit_text("📜 Majburiy obuna kanallari mavjud emas.")
        return

    text = "📜 <b>Ullangan Kanallar Ro'yxati:</b>\n\n"
    for c in channels:
        text += f"• <b>{c['title']}</b> | ID: <code>{c['channel_id']}</code>\n🔗 {c['link']}\n\n"

    await callback.message.edit_text(text, parse_mode="HTML")


# ==================== BAN TIZIMI ====================

@dp.callback_query(F.data == "admin_ban_menu")
async def ban_menu_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Foydalanuvchini bloklash", callback_data="ban_user")],
        [InlineKeyboardButton(text="✅ Blokdan chiqarish", callback_data="unban_user")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back_main")]
    ])
    await callback.message.edit_text("🚫 <b>Foydalanuvchilarni Bloklash Boshqaruvi</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "ban_user")
async def start_ban_user(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_ban_id)
    await callback.message.edit_text("🚫 Bloklamoqchi bo'lgan foydalanuvchining **Telegram ID**sini yuboring:")


@dp.message(AdminStates.waiting_for_ban_id)
async def process_ban_user(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Telegram ID raqamlardan iborat bo'lishi kerak.")
        return

    uid = int(message.text)
    if uid == SUPER_ADMIN_ID or await is_admin(uid):
        await message.answer("⚠️ Adminlarni bloklash imkonsiz!")
        return

    await db.set_user_ban_status(uid, is_banned=True)
    await state.clear()
    await message.answer(f"🚫 Foydalanuvchi <code>{uid}</code> botdan bloklandi.", parse_mode="HTML")


@dp.callback_query(F.data == "unban_user")
async def start_unban_user(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_unban_id)
    await callback.message.edit_text("✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchining **Telegram ID**sini yuboring:")


@dp.message(AdminStates.waiting_for_unban_id)
async def process_unban_user(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Telegram ID raqamlardan iborat bo'lishi kerak.")
        return

    uid = int(message.text)
    await db.set_user_ban_status(uid, is_banned=False)
    await state.clear()
    await message.answer(f"✅ Foydalanuvchi <code>{uid}</code> blokdan chiqarildi.", parse_mode="HTML")


# ==================== BROADCAST (XABAR YUBORISH) ====================

@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return

    await state.set_state(AdminStates.waiting_for_broadcast_msg)
    await callback.message.edit_text(
        "📢 <b>Broadcast Bo'limi</b>\n\n"
        "Foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring (Matn, Rasm, Video yoki Fayl):\n\n"
        "Bekor qilish uchun /cancel bosing.",
        parse_mode="HTML"
    )


@dp.message(AdminStates.waiting_for_broadcast_msg)
async def process_broadcast_message(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    await state.set_state(AdminStates.waiting_for_broadcast_btn_ask)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ha", callback_data="bc_add_btn_yes")],
        [InlineKeyboardButton(text="Yo'q", callback_data="bc_add_btn_no")]
    ])

    await message.answer("➕ Xabar ostiga URL tugma qo'shilsinmi?", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(AdminStates.waiting_for_broadcast_btn_ask, F.data == "bc_add_btn_no")
async def broadcast_without_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    await callback.message.edit_text("⏳ Broadcast boshlandi...")
    
    user_ids = await db.get_all_active_user_ids()
    success, failed = 0, 0

    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=data["broadcast_chat_id"],
                message_id=data["broadcast_message_id"]
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)

    await callback.message.answer(
        f"✅ <b>Broadcast Yakunlandi!</b>\n\n"
        f"🟢 Muvaffaqiyatli: {success} ta\n"
        f"🔴 Etib bormadi: {failed} ta",
        parse_mode="HTML"
    )


@dp.callback_query(AdminStates.waiting_for_broadcast_btn_ask, F.data == "bc_add_btn_yes")
async def ask_button_details(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_broadcast_btn_details)
    await callback.message.edit_text(
        "Tugma matni va havolasini ushbu formatda kiriting:\n\n"
        "<code>Tugma Nomi + https://t.me/link</code>",
        parse_mode="HTML"
    )


@dp.message(AdminStates.waiting_for_broadcast_btn_details)
async def process_button_and_send(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    text = message.text.strip()
    if "+" not in text:
        await message.answer("⚠️ Noto'g'ri format! Iltimos, <code>Tugma Nomi + link</code> ko'rinishida yuboring.")
        return

    try:
        btn_text, btn_url = map(str.strip, text.split("+", 1))
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, url=btn_url)]
        ])
    except Exception:
        await message.answer("⚠️ Havola tuzilishida xatolik yuz berdi.")
        return

    data = await state.get_data()
    await state.clear()

    await message.answer("⏳ Broadcast boshlandi...")

    user_ids = await db.get_all_active_user_ids()
    success, failed = 0, 0

    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=data["broadcast_chat_id"],
                message_id=data["broadcast_message_id"],
                reply_markup=reply_markup
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)

    await message.answer(
        f"✅ <b>Broadcast Tugma Bilan Yakunlandi!</b>\n\n"
        f"🟢 Muvaffaqiyatli: {success} ta\n"
        f"🔴 Etib bormadi: {failed} ta",
        parse_mode="HTML"
    )


# ==================== AUTOMATION (KANAL POSTLARINI TUSHIRISH) ====================

@dp.channel_post(F.chat.id == CHANNEL_ID)
async def auto_save_channel_movie(message: Message):
    text = message.caption or message.text or ""
    
    quality_match = re.search(r'#(1080p|720p|480p|360p|1080|720|480|360)\b', text, re.IGNORECASE)
    code_match = re.search(r'(?:kino\s*kodi|kodi|kod|code)\s*[:=\-]?\s*#?(\d+)', text, re.IGNORECASE)
    
    if not code_match:
        code_match = re.search(r'#(\d+)\b', text)
    
    if code_match:
        movie_code = code_match.group(1)
        quality = quality_match.group(1).lower().replace("p", "") if quality_match else "720"
        
        saved = await db.save_movie_quality(
            code=movie_code,
            quality=quality,
            message_id=message.message_id,
            caption=text
        )
        if saved:
            logging.info(f"✅ Kino saqlandi: Kod - #{movie_code}, Sifat - {quality}p, Msg ID - {message.message_id}")


# ==================== FOYDALANUVCHI BO'LIMI ====================

@dp.message(CommandStart())
async def start_handler(message: Message):
    if await db.is_user_banned(message.from_user.id):
        await message.answer("🚫 Siz botdan foydalanishdan cheklangansiz!")
        return

    await db.add_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username
    )

    if not await is_user_subscribed(message.from_user.id):
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>",
            reply_markup=await check_subscription_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"Assalomu alaykum, <b>{message.from_user.full_name}</b>!\n\n"
        "Bizning rasmiy kino botimizga xush kelibsiz.\n"
        "Kino olish uchun shunchaki <b>kino kodini (masalan: 123)</b> yozib yuboring!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await is_user_subscribed(callback.from_user.id):
        await callback.answer("✅ Rahmat! Obuna tasdiqlandi.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("Bosh menyu:\nKino kodini yozib yuborishingiz mumkin.", reply_markup=main_menu_keyboard())
    else:
        await callback.answer("❌ Siz hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)


@dp.message(F.text == "🎬 Kino izlash")
async def ask_movie_code(message: Message):
    if await db.is_user_banned(message.from_user.id):
        return

    if not await is_user_subscribed(message.from_user.id):
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>",
            reply_markup=await check_subscription_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        "💡 <b>Kino izlash juda oson!</b>\n\n"
        "Shunchaki kino kodini (masalan: <code>123</code>) yozib yuboring.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@dp.message(F.text == "ℹ️ Bot haqida")
async def about_handler(message: Message):
    if await db.is_user_banned(message.from_user.id):
        return

    if not await is_user_subscribed(message.from_user.id):
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>",
            reply_markup=await check_subscription_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        "🤖 <b>Kino Bot Tizimi</b>\n\n"
        "Ushbu bot orqali kanaldagi barcha kinolarni turli sifatlarda tezkor yuklab olishingiz mumkin.",
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("get_quality:"))
async def send_movie_by_quality(callback: CallbackQuery):
    if await db.is_user_banned(callback.from_user.id):
        await callback.answer("🚫 Siz bloklangansiz!", show_alert=True)
        return

    if not await is_user_subscribed(callback.from_user.id):
        await callback.answer("⚠️ Botdan foydalanish uchun kanallarga a'zo bo'ling!", show_alert=True)
        return

    parts = callback.data.split(":")
    code, quality = parts[1], parts[2]

    movie = await db.get_movie(code=code)
    if not movie or not movie.get(f"msg_{quality}"):
        await callback.answer("❌ Fayl topilmadi!", show_alert=True)
        return

    try:
        await bot.copy_message(
            chat_id=callback.message.chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=movie[f"msg_{quality}"]
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Kino yuborishda xatolik: {e}")
        await callback.answer("❌ Kinoni yuborishda xatolik yuz berdi.", show_alert=True)


@dp.message(F.text)
async def handle_all_messages(message: Message):
    if await db.is_user_banned(message.from_user.id):
        return

    if not await is_user_subscribed(message.from_user.id):
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>",
            reply_markup=await check_subscription_keyboard(),
            parse_mode="HTML"
        )
        return

    user_input = message.text.strip().replace("#", "")

    if user_input.isdigit():
        movie = await db.get_movie(code=user_input)
        if movie:
            buttons = []
            for q, icon in [("360", "📲"), ("480", "📱"), ("720", "🎬"), ("1080", "🖥")]:
                if movie.get(f"msg_{q}"):
                    buttons.append(InlineKeyboardButton(text=f"{icon} {q}p", callback_data=f"get_quality:{user_input}:{q}"))

            if buttons:
                kb = InlineKeyboardMarkup(inline_keyboard=[buttons])
                raw_caption = movie.get("caption") or f"🎬 Kino kodi: {user_input}"
                await message.answer(
                    f"{raw_caption}\n\n👇 <b>Kerakli sifatni tanlang:</b>",
                    parse_mode="HTML",
                    reply_markup=kb
                )
            else:
                await message.answer("❌ Ushbu kino uchun hech qanday fayl topilmadi.")
        else:
            await message.answer(
                f"❌ Afsuski, <b>{user_input}</b>-kodli kino topilmadi.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
    else:
        await message.answer(
            "⚠️ <b>Noma'lum so'rov!</b>\n\nIltimos, faqat kino kodini yozing.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )


async def main():
    print("Bot va Admin Dashboard API orqali muvaffaqiyatli ishga tushdi...")
    try:
        await dp.start_polling(bot)
    finally:
        global session
        if session and not session.closed:
            await session.close()


if __name__ == "__main__":
    asyncio.run(main())
