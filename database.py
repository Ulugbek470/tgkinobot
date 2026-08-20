import logging
import aiosqlite
from typing import Optional, Dict, List, Tuple, Any

DB_NAME = "bot_database.db"

# Loglarni sozlash
logger = logging.getLogger(__name__)


async def init_db() -> None:

    """Ma'lumotlar bazasi, jadvallar, ustunlar va indekslarni yaratish."""

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # WAL rejimini yoqish (baza qulflanib qolmasligi uchun)
            await db.execute("PRAGMA journal_mode=WAL;")

            # Foydalanuvchilar jadvali
            await db.execute("""

                CREATE TABLE IF NOT EXISTS users (

                    user_id INTEGER PRIMARY KEY,

                    full_name TEXT NOT NULL,

                    username TEXT,

                    is_banned INTEGER DEFAULT 0,

                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

                )

            """)

            # Kinolar jadvali
            await db.execute("""

                CREATE TABLE IF NOT EXISTS movies (

                    code TEXT PRIMARY KEY,

                    msg_360 INTEGER DEFAULT NULL,

                    msg_480 INTEGER DEFAULT NULL,

                    msg_720 INTEGER DEFAULT NULL,

                    msg_1080 INTEGER DEFAULT NULL,

                    caption TEXT

                )

            """)

            # Adminlar jadvali
            await db.execute("""

                CREATE TABLE IF NOT EXISTS admins (

                    user_id INTEGER PRIMARY KEY

                )

            """)

            # Majburiy obuna kanallari jadvali
            await db.execute("""

                CREATE TABLE IF NOT EXISTS channels (

                    channel_id INTEGER PRIMARY KEY,

                    title TEXT NOT NULL,

                    link TEXT NOT NULL

                )

            """)

            # Migratsiyalar (Eski bazalarda ustunlar bo'lmasa avtomatik qo'shish)
            try:
                await db.execute("ALTER TABLE movies ADD COLUMN msg_360 INTEGER DEFAULT NULL;")
            except Exception:
                pass

            try:
                await db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0;")
            except Exception:
                pass

            # Indekslar
            await db.execute("CREATE INDEX IF NOT EXISTS idx_movies_code ON movies(code);")

            await db.commit()
            logger.info("Database muvaffaqiyatli ishga tushirildi.")
    except Exception as e:
        logger.error(f"Database init xatosi: {e}")
        raise e


# ==================== USER OPERATIONS ====================


async def add_user(user_id: int, full_name: str, username: Optional[str] = None) -> bool:

    """Foydalanuvchini bazaga qo'shadi yoki ma'lumotlarini yangilaydi."""

    query = """

        INSERT INTO users (user_id, full_name, username)

        VALUES (?, ?, ?)

        ON CONFLICT(user_id) DO UPDATE SET

            full_name = excluded.full_name,

            username = excluded.username

    """
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(query, (user_id, full_name, username))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"User qo'shishda xatolik ({user_id}): {e}")
        return False


async def is_user_banned(user_id: int) -> bool:

    """Foydalanuvchi ban qilinganligini tekshiradi."""

    query = "SELECT is_banned FROM users WHERE user_id = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return bool(row[0]) if row and row[0] is not None else False
    except Exception as e:
        logger.error(f"Ban tekshirishda xatolik ({user_id}): {e}")
        return False


async def set_user_ban_status(user_id: int, is_banned: bool) -> bool:

    """Foydalanuvchini ban qilish yoki bandan chiqarish."""

    query = "UPDATE users SET is_banned = ? WHERE user_id = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(query, (1 if is_banned else 0, user_id))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ban holatini o'zgartirishda xatolik ({user_id}): {e}")
        return False


async def get_all_active_user_ids() -> List[int]:

    """Bloklanmagan barcha foydalanuvchilar ID larini olish (Broadcast uchun)."""

    query = "SELECT user_id FROM users WHERE is_banned = 0 OR is_banned IS NULL"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Aktiv User ID larni olishda xatolik: {e}")
        return []


async def get_all_user_ids() -> List[int]:

    """Barcha foydalanuvchilar ID larini olish."""

    query = "SELECT user_id FROM users"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"User ID larni olishda xatolik: {e}")
        return []


async def get_stats() -> Tuple[int, int]:

    """Oddiy statistika (Foydalanuvchilar va Kinolar soni)."""

    query_users = "SELECT COUNT(*) FROM users"
    query_movies = "SELECT COUNT(*) FROM movies"

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query_users) as c1:
                users_count = (await c1.fetchone())[0]
            async with db.execute(query_movies) as c2:
                movies_count = (await c2.fetchone())[0]
            return users_count, movies_count
    except Exception as e:
        logger.error(f"Statistika olishda xatolik: {e}")
        return 0, 0


async def get_extended_stats() -> Tuple[int, int, int]:

    """Kengaytirilgan statistika (Foydalanuvchilar, Kinolar va Bloklanganlar soni)."""

    query_users = "SELECT COUNT(*) FROM users"
    query_movies = "SELECT COUNT(*) FROM movies"
    query_banned = "SELECT COUNT(*) FROM users WHERE is_banned = 1"

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query_users) as c1:
                users_count = (await c1.fetchone())[0]
            async with db.execute(query_movies) as c2:
                movies_count = (await c2.fetchone())[0]
            async with db.execute(query_banned) as c3:
                banned_count = (await c3.fetchone())[0]
            return users_count, movies_count, banned_count
    except Exception as e:
        logger.error(f"Kengaytirilgan statistika olishda xatolik: {e}")
        return 0, 0, 0


# ==================== MOVIE OPERATIONS ====================


async def save_movie_quality(code: str, quality: str, message_id: int, caption: str = "") -> bool:

    """Muayyan sifatdagi kinoni saqlaydi."""

    allowed_qualities = {"360": "msg_360", "480": "msg_480", "720": "msg_720", "1080": "msg_1080"}
    quality_str = str(quality)

    if quality_str not in allowed_qualities:
        logger.error(f"Noto'g'ri sifat kiritildi: {quality}")
        return False

    quality_col = allowed_qualities[quality_str]

    query = f"""

        INSERT INTO movies (code, {quality_col}, caption)

        VALUES (?, ?, ?)

        ON CONFLICT(code) DO UPDATE SET

            {quality_col} = excluded.{quality_col},

            caption = CASE 

                WHEN excluded.caption IS NOT NULL AND excluded.caption != '' THEN excluded.caption 

                ELSE movies.caption 

            END

    """
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(query, (str(code), message_id, caption))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Sifat bo'yicha kino saqlashda xatolik (Kod: {code}, Sifat: {quality}): {e}")
        return False


async def get_movie(code: str) -> Optional[Dict[str, Any]]:

    """Kino kodi bo'yicha barcha sifatlar va caption'ni oladi."""

    query = "SELECT msg_360, msg_480, msg_720, msg_1080, caption FROM movies WHERE code = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query, (str(code),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "msg_360": row[0],
                        "msg_480": row[1],
                        "msg_720": row[2],
                        "msg_1080": row[3],
                        "caption": row[4]
                    }
                return None
    except Exception as e:
        logger.error(f"Kino izlashda xatolik (Kod: {code}): {e}")
        return None


async def delete_movie(code: str) -> bool:

    """Kino kodiga ko'ra kinoni bazadan to'liq o'chirish."""

    query = "DELETE FROM movies WHERE code = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query, (str(code),)) as cursor:
                deleted = cursor.rowcount > 0
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"Kino o'chirishda xatolik (Kod: {code}): {e}")
        return False


# ==================== ADMIN OPERATIONS ====================


async def add_admin_user(user_id: int) -> bool:

    """Admin qo'shish."""

    query = "INSERT OR IGNORE INTO admins (user_id) VALUES (?)"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(query, (user_id,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Admin qo'shishda xatolik ({user_id}): {e}")
        return False


async def remove_admin_user(user_id: int) -> bool:

    """Adminni o'chirish."""

    query = "DELETE FROM admins WHERE user_id = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query, (user_id,)) as cursor:
                deleted = cursor.rowcount > 0
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"Admin o'chirishda xatolik ({user_id}): {e}")
        return False


async def get_admin_list() -> List[int]:

    """Adminlar ID ro'yxatini olish."""

    query = "SELECT user_id FROM admins"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Adminlar ro'yxatini olishda xatolik: {e}")
        return []


# ==================== CHANNEL OPERATIONS ====================


async def add_channel(channel_id: int, title: str, link: str) -> bool:

    """Majburiy obuna kanalini qo'shish."""

    query = """

        INSERT INTO channels (channel_id, title, link)

        VALUES (?, ?, ?)

        ON CONFLICT(channel_id) DO UPDATE SET

            title = excluded.title,

            link = excluded.link

    """
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(query, (channel_id, title, link))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Kanal qo'shishda xatolik ({channel_id}): {e}")
        return False


async def remove_channel(channel_id: int) -> bool:

    """Kanalni majburiy obunadan o'chirish."""

    query = "DELETE FROM channels WHERE channel_id = ?"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query, (channel_id,)) as cursor:
                deleted = cursor.rowcount > 0
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"Kanal o'chirishda xatolik ({channel_id}): {e}")
        return False


async def get_active_channels() -> List[Dict[str, Any]]:

    """Faol majburiy obuna kanallari ro'yxatini olish."""

    query = "SELECT channel_id, title, link FROM channels"
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [
                    {"channel_id": row[0], "title": row[1], "link": row[2]}
                    for row in rows
                ]
    except Exception as e:
        logger.error(f"Kanallar ro'yxatini olishda xatolik: {e}")
        return []
