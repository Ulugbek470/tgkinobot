import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Baza turini aniqlash (PostgreSQL yoki SQLite)
DATABASE_URL = os.getenv("DATABASE_URL")

async def init_postgres():
    import asyncpg
    
    # Render'dagi postgres:// ni postgresql:// ga o'tkazish
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    conn = await asyncpg.connect(db_url)
    try:
        # 1. Jadvalni yaratish
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        logger.info(" PostgreSQL: 'movies' jadvali tekshirildi/yaratildi.")

        # 2. Ustunlar mavjudligini tekshirish va yo'q bo'lsa qo'shish (Migration logic)
        required_columns = {
            "title": "VARCHAR(255)",
            "genre": "VARCHAR(255)",
            "language": "VARCHAR(100)",
            "channel": "VARCHAR(255)",
            "msg_360": "BIGINT",
            "msg_480": "BIGINT",
            "msg_720": "BIGINT",
            "msg_1080": "BIGINT",
        }

        # Mavjud ustunlarni olish
        existing_cols = await conn.fetch("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='movies';
        """)
        existing_col_names = [col['column_name'] for col in existing_cols]

        for col_name, col_type in required_columns.items():
            if col_name not in existing_col_names:
                await conn.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_type};")
                logger.info(f" PostgreSQL: Yangi ustun qo'shildi -> {col_name}")

    finally:
        await conn.close()


async def init_sqlite():
    import aiosqlite
    db_path = os.getenv("DB_PATH", "bot_database.db")
    
    async with aiosqlite.connect(db_path) as db:
        # 1. Jadvalni yaratish
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.commit()
        logger.info(" SQLite: 'movies' jadvali tekshirildi/yaratildi.")

        # 2. Ustunlarni tekshirish va qo'shish
        async with db.execute("PRAGMA table_info(movies);") as cursor:
            rows = await cursor.fetchall()
            existing_col_names = [row[1] for row in rows]

        required_columns = {
            "title": "TEXT",
            "genre": "TEXT",
            "language": "TEXT",
            "channel": "TEXT",
            "msg_360": "INTEGER",
            "msg_480": "INTEGER",
            "msg_720": "INTEGER",
            "msg_1080": "INTEGER",
        }

        for col_name, col_type in required_columns.items():
            if col_name not in existing_col_names:
                await db.execute(f"ALTER TABLE movies ADD COLUMN {col_name} {col_type};")
                await db.commit()
                logger.info(f" SQLite: Yangi ustun qo'shildi -> {col_name}")


async def create_db():
    if DATABASE_URL:
        logger.info("PostgreSQL bazasiga ulaninsh va tekshirish boshlandi...")
        await init_postgres()
    else:
        logger.info("SQLite bazasiga ulanish va tekshirish boshlandi...")
        await init_sqlite()
    
    logger.info(" Baza va barcha ustunlar tayyor!")

if __name__ == "__main__":
    asyncio.run(create_db())
