import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
SUPER_ADMIN_ID = os.getenv("ADMIN_ID") or os.getenv("SUPER_ADMIN_ID")


# ==================== POSTGRESQL INIZIALIZATSIYASI ====================

async def init_postgres():
    import asyncpg

    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    conn = await asyncpg.connect(db_url)
    try:
        # 1. Foydalanuvchilar jadvali
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                username VARCHAR(255),
                is_banned INT DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Kinolar jadvali
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                title VARCHAR(255),
                genre VARCHAR(255),
                language VARCHAR(100),
                channel VARCHAR(255),
                msg_360 BIGINT,
                msg_480 BIGINT,
                msg_720 BIGINT,
                msg_1080 BIGINT,
                caption TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Adminlar jadvali
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Kanallar jadvali (Yangilangan)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id BIGINT PRIMARY KEY,
                title VARCHAR(255),
                link VARCHAR(255),
                invite_link VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        logger.info("🟢 PostgreSQL: Barcha jadvallar muvaffaqiyatli yaratildi/tekshirildi.")

        # --- MOVIES MIGRATSIYA ---
        required_movie_columns = {
            "title": "VARCHAR(255)",
            "genre": "VARCHAR(255)",
            "language": "VARCHAR(100)",
            "channel": "VARCHAR(255)",
            "msg_360": "BIGINT",
            "msg_480": "BIGINT",
            "msg_720": "BIGINT",
            "msg_1080": "BIGINT",
            "caption": "TEXT"
        }

        existing_movie_cols = await conn.fetch("""
            SELECT column_name FROM information_schema.columns WHERE table_name='movies';
        """)
        existing_movie_col_names = [col['column_name'] for col in existing_movie_cols]

        for col_name, col_type in required_movie_columns.items():
            if col_name not in existing_movie_col_names:
                await conn.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_type};")
                logger.info(f"🔄 PostgreSQL: 'movies' ga ustun qo'shildi -> {col_name}")

        # --- CHANNELS MIGRATSIYA ---
        required_channel_columns = {
            "title": "VARCHAR(255)",
            "link": "VARCHAR(255)",
            "invite_link": "VARCHAR(255)"
        }

        existing_channel_cols = await conn.fetch("""
            SELECT column_name FROM information_schema.columns WHERE table_name='channels';
        """)
        existing_channel_col_names = [col['column_name'] for col in existing_channel_cols]

        for col_name, col_type in required_channel_columns.items():
            if col_name not in existing_channel_col_names:
                await conn.execute(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type};")
                logger.info(f"🔄 PostgreSQL: 'channels' ga ustun qo'shildi -> {col_name}")

        # Super Adminni kiritish
        if SUPER_ADMIN_ID:
            admin_id = int(SUPER_ADMIN_ID)
            await conn.execute("""
                INSERT INTO admins (user_id) 
                VALUES ($1) 
                ON CONFLICT (user_id) DO NOTHING;
            """, admin_id)

    except Exception as e:
        logger.error(f"❌ PostgreSQL xatosi: {e}")
        raise e
    finally:
        await conn.close()


# ==================== SQLITE INIZIALIZATSIYASI ====================

async def init_sqlite():
    import aiosqlite
    db_path = os.getenv("DB_PATH", "bot_database.db")

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                username TEXT,
                is_banned INTEGER DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                title TEXT,
                genre TEXT,
                language TEXT,
                channel TEXT,
                msg_360 INTEGER,
                msg_480 INTEGER,
                msg_720 INTEGER,
                msg_1080 INTEGER,
                caption TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                title TEXT,
                link TEXT,
                invite_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.commit()

        # --- MOVIES MIGRATSIYA ---
        async with db.execute("PRAGMA table_info(movies);") as cursor:
            rows = await cursor.fetchall()
            existing_movie_cols = [row[1] for row in rows]

        required_movie_columns = {
            "title": "TEXT",
            "genre": "TEXT",
            "language": "TEXT",
            "channel": "TEXT",
            "msg_360": "INTEGER",
            "msg_480": "INTEGER",
            "msg_720": "INTEGER",
            "msg_1080": "INTEGER",
            "caption": "TEXT"
        }

        for col_name, col_type in required_movie_columns.items():
            if col_name not in existing_movie_cols:
                await db.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_type};")
                await db.commit()

        # --- CHANNELS MIGRATSIYA ---
        async with db.execute("PRAGMA table_info(channels);") as cursor:
            rows = await cursor.fetchall()
            existing_channel_cols = [row[1] for row in rows]

        required_channel_columns = {
            "title": "TEXT",
            "link": "TEXT",
            "invite_link": "TEXT"
        }

        for col_name, col_type in required_channel_columns.items():
            if col_name not in existing_channel_cols:
                await db.execute(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type};")
                await db.commit()
                logger.info(f"🔄 SQLite: 'channels' ga ustun qo'shildi -> {col_name}")

        if SUPER_ADMIN_ID:
            admin_id = int(SUPER_ADMIN_ID)
            await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?);", (admin_id,))
            await db.commit()


# ==================== MAIN RUNNER ====================

async def create_db():
    if DATABASE_URL:
        logger.info("📡 PostgreSQL bazasi va jadvallari tekshirilmoqda...")
        await init_postgres()
    else:
        logger.info("📁 SQLite bazasi va jadvallari tekshirilmoqda...")
        await init_sqlite()

    logger.info("✅ Baza va 'channels' jadvali muvaffaqiyatli yangilandi!")


if __name__ == "__main__":
    asyncio.run(create_db())
