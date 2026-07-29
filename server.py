import os
import json
import random
import time
import hashlib
import hmac
from urllib.parse import unquote
from datetime import datetime, timezone
import aiosqlite
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE = "game.db"
BOT_TOKEN = os.getenv("7955684710:AAGcGV3C8Zcb0TQx1P7a5BQSK1BRle-sCss", "7955684710:AAGcGV3C8Zcb0TQx1P7a5BQSK1BRle-sCss")  # замени на токен от @BotFather

# ======= Инициализация базы =======
async def get_db():
    db = await aiosqlite.connect(DATABASE)
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                blocked INTEGER DEFAULT 0,
                stars INTEGER DEFAULT 100,
                total_games INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                total_losses INTEGER DEFAULT 0,
                last_daily_claim TEXT DEFAULT '2000-01-01T00:00:00',
                used_promo_codes TEXT DEFAULT '[]',
                inventory TEXT DEFAULT '[]',
                subscription_verified INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referral_earnings INTEGER DEFAULT 0,
                used_velo_code INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id TEXT NOT NULL,
                referred_id TEXT NOT NULL UNIQUE,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_views (
                user_id TEXT NOT NULL,
                broadcast_id INTEGER NOT NULL,
                viewed INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, broadcast_id)
            )
        """)
        await db.commit()

@app.on_event("startup")
async def startup():
    await init_db()

# ======= Проверка Telegram initData =======
def verify_telegram(init_data: str) -> bool:
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        return True  # для тестов без валидации
    try:
        vals = {k: unquote(v) for k, v in [s.split('=') for s in init_data.split('&')]}
        data_check = '\n'.join(f"{k}={v}" for k, v in sorted(vals.items()) if k != 'hash')
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        h = hmac.new(secret, data_check.encode(), hashlib.sha256)
        return h.hexdigest() == vals.get('hash', '')
    except:
        return False

# ======= Модели запросов =======
class BalanceUpdate(BaseModel):
    user_id: str
    delta: int

class AddItem(BaseModel):
    user_id: str
    item: dict

class PromoCodeReq(BaseModel):
    user_id: str
    code: str

class BroadcastReq(BaseModel):
    admin_id: str
    message: str

class ReferralReq(BaseModel):
    referrer_id: str
    referred_id: str

# ======= API эндпоинты =======
@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
        user = await cursor.fetchone()
    if not user:
        # Создаём нового
        await db.execute("INSERT INTO users (user_id, name) VALUES (?, ?)", (user_id, f"User{user_id[:5]}"))
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
    await db.close()
    return dict(user)

@app.post("/api/update_balance")
async def update_balance(data: BalanceUpdate, request: Request):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE user_id = ?", (data.user_id,)) as cursor:
        user = await cursor.fetchone()
    if not user:
        await db.close()
        raise HTTPException(404, "User not found")
    if user['blocked']:
        await db.close()
        raise HTTPException(403, "Blocked")
    new_stars = user['stars'] + data.delta
    if new_stars < 0:
        await db.close()
        raise HTTPException(400, "Insufficient stars")
    await db.execute("UPDATE users SET stars = ?, total_games = total_games + 1 WHERE user_id = ?",
                     (new_stars, data.user_id))
    await db.commit()
    await db.close()
    return {"status": "ok", "stars": new_stars}

@app.post("/api/add_item")
async def add_item(data: AddItem):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE user_id = ?", (data.user_id,)) as cursor:
        user = await cursor.fetchone()
    if not user:
        await db.close()
        raise HTTPException(404, "User not found")
    inventory = json.loads(user['inventory']) if user['inventory'] else []
    inventory.append(data.item)
    await db.execute("UPDATE users SET inventory = ? WHERE user_id = ?",
                     (json.dumps(inventory), data.user_id))
    await db.commit()
    await db.close()
    return {"status": "ok"}

@app.post("/api/use_promo")
async def use_promo(req: PromoCodeReq):
    VALID_CODES = ['Бурмалда','Павел','Матвей','Скебоб','67','Стефан','Даша','Саша','ВелоДрун']
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE user_id = ?", (req.user_id,)) as cursor:
        user = await cursor.fetchone()
    if not user:
        await db.close()
        raise HTTPException(404, "User not found")
    if req.code not in VALID_CODES:
        await db.close()
        raise HTTPException(400, "Invalid code")
    used = json.loads(user['used_promo_codes']) if user['used_promo_codes'] else []
    if req.code in used:
        await db.close()
        raise HTTPException(400, "Already used")
    reward = 50 + (abs(hash(req.code)) % 200)
    used.append(req.code)
    await db.execute("UPDATE users SET stars = stars + ?, used_promo_codes = ? WHERE user_id = ?",
                     (reward, json.dumps(used), req.user_id))
    await db.commit()
    await db.close()
    return {"status": "ok", "reward": reward}

@app.post("/api/broadcast")
async def send_broadcast(data: BroadcastReq):
    ADMIN_IDS = ['8183675472', '5731537463']
    if data.admin_id not in ADMIN_IDS:
        raise HTTPException(403, "Not admin")
    db = await get_db()
    await db.execute("INSERT INTO broadcasts (message) VALUES (?)", (data.message,))
    await db.commit()
    await db.close()
    return {"status": "ok"}

@app.get("/api/broadcast/{user_id}")
async def get_broadcasts(user_id: str):
    db = await get_db()
    # выбираем непрочитанные
    cursor = await db.execute("""
        SELECT b.id, b.message FROM broadcasts b
        WHERE b.id NOT IN (
            SELECT broadcast_id FROM broadcast_views WHERE user_id = ? AND viewed = 1
        )
    """, (user_id,))
    rows = await cursor.fetchall()
    for row in rows:
        await db.execute("INSERT OR REPLACE INTO broadcast_views (user_id, broadcast_id, viewed) VALUES (?, ?, 1)",
                         (user_id, row['id']))
    await db.commit()
    await db.close()
    return {"messages": [{"id": r['id'], "message": r['message']} for r in rows]}

@app.post("/api/process_referral")
async def process_referral(data: ReferralReq):
    db = await get_db()
    # проверяем, существует ли уже запись
    cursor = await db.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (data.referred_id,))
    if await cursor.fetchone():
        await db.close()
        return {"status": "already"}
    await db.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                     (data.referrer_id, data.referred_id))
    await db.execute("UPDATE users SET stars = stars + 1, referral_count = referral_count + 1, referral_earnings = referral_earnings + 1 WHERE user_id = ?",
                     (data.referrer_id,))
    await db.commit()
    await db.close()
    return {"status": "ok"}

# ======= Раздача статики (HTML) =======
# Файл index.html должен лежать в той же папке, что и server.py
app.mount("/", StaticFiles(directory=".", html=True), name="static")