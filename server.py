import sqlite3
import random
import time
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from aiogram.types import LabeledPrice
from bot import bot

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "market.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 1500.0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            luck_multi REAL DEFAULT 1.0,
            luck_until INTEGER DEFAULT 0,
            ref_by INTEGER DEFAULT NULL,
            refs_count INTEGER DEFAULT 0,
            smm_lvl INTEGER DEFAULT 1,
            buyer_lvl INTEGER DEFAULT 0,
            last_claim INTEGER DEFAULT 0,
            created_at INTEGER
        )
    """)
    # Таблица тегов (ХОЛД)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            tag TEXT PRIMARY KEY,
            owner_id INTEGER,
            rarity TEXT,
            income_per_sec REAL,
            sell_price REAL,
            reasons TEXT,
            is_equipped INTEGER DEFAULT 0,
            created_at INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(tg_user_id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 1. БАЗЫ СЛОВ И РЕДКОСТЕЙ (10 ТИРОВ)
# ==========================================
WORDS_DIVINE = ["x", "v", "ai", "go", "ok", "up", "7"]
WORDS_EXCLUSIVE = ["durov", "telegram", "ton", "notcoin", "pavel", "vk", "redo"]
WORDS_ULTRA = ["cat", "dog", "bot", "nft", "god", "top", "ceo"]
WORDS_LUXURY = ["dubai", "money", "rich", "gold", "boss", "king", "stars"]
WORDS_MYTHIC = ["star", "epic", "moon", "flow", "dark", "litvin", "mellstroy", "mrbeast"]
WORDS_LEGENDARY = ["tiger", "ghost", "alpha", "prime", "whale", "wylsa", "subo", "buster"]
WORDS_EPIC = ["shadow", "crypto", "hacker", "sniper", "ninja", "blade"]
WORDS_RARE = ["gamer", "player", "rocket", "market", "trade", "speed"]
WORDS_UNCOMMON = ["user", "pro", "hero", "fan", "club"]

RARITIES = [
    {"name": "Common",       "w": 70000, "inc": 1,      "xp": 5,     "sell": 50},
    {"name": "Uncommon",     "w": 20000, "inc": 5,      "xp": 15,    "sell": 250},
    {"name": "Rare",         "w": 7000,  "inc": 15,     "xp": 40,    "sell": 750},
    {"name": "Epic",         "w": 2000,  "inc": 50,     "xp": 100,   "sell": 2500},
    {"name": "Legendary",    "w": 600,   "inc": 200,    "xp": 300,   "sell": 10000},
    {"name": "Mythic",       "w": 200,   "inc": 450,    "xp": 800,   "sell": 25000},
    {"name": "Luxury",       "w": 60,    "inc": 1200,   "xp": 1500,  "sell": 75000},
    {"name": "Ultra-Mythic", "w": 20,    "inc": 4000,   "xp": 2500,  "sell": 200000},
    {"name": "Exclusive",    "w": 6,     "inc": 15000,  "xp": 5000,  "sell": 800000},
    {"name": "Divine",       "w": 1,     "inc": 100000, "xp": 15000, "sell": 3000000}
]

SPIN_MODES = {
    "basic":   {"cost": 100,  "min_idx": 0},
    "silver":  {"cost": 300,  "min_idx": 1},
    "gold":    {"cost": 1000, "min_idx": 2},
    "diamond": {"cost": 5000, "min_idx": 3}
}

# ==========================================
# 2. ДВИЖОК ГЕНЕРАЦИИ ТЕГОВ (СЕРВЕРНЫЙ)
# ==========================================
def generate_tag_logic(cur, mode, luck_multi):
    min_idx = SPIN_MODES[mode]["min_idx"]
    pool = []
    total_w = 0
    
    # Удача умножает шансы на Эпик и выше
    for i, r in enumerate(RARITIES):
        if i >= min_idx:
            weight = r["w"]
            if i >= 3: weight = int(weight * luck_multi)
            pool.append({"data": r, "w": weight})
            total_w += weight

    rnd = random.random() * total_w
    picked = pool[0]["data"]
    for p in pool:
        if rnd < p["w"]:
            picked = p["data"]
            break
        rnd -= p["w"]

    rarity = picked["name"]
    reasons = []
    
    def get_word(word_list):
        # Ищем свободный эксклюзив
        random.shuffle(word_list)
        for w in word_list:
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (f"@{w}",))
            if not cur.fetchone(): return w
        return None

    word = None
    if rarity == "Divine":
        word = get_word(WORDS_DIVINE)
        if word: reasons = ["👑 Ультра-короткий (2 буквы)", "🚫 Без цифр и символов", "✨ Высшая ценность"]
    elif rarity == "Exclusive":
        word = get_word(WORDS_EXCLUSIVE)
        if word: reasons = [f"💎 Бренд / Знаменитость ({word})", "🚫 Без цифр", "✨ Уникальный эксклюзив"]
    elif rarity == "Ultra-Mythic":
        word = get_word(WORDS_ULTRA)
        if word: reasons = ["🔥 3 буквы", "🚫 Без цифр", "✅ Премиальный статус"]
    elif rarity == "Luxury":
        word = get_word(WORDS_LUXURY)
        if word: reasons = ["💰 Роскошное слово (Luxury)", "🚫 Без цифр", "✅ Высокий спрос на рынке"]
    elif rarity == "Mythic":
        word = get_word(WORDS_MYTHIC)
        if word: reasons = ["⭐ 4 буквы / Топ Блогер", "🚫 Без цифр"]
    elif rarity == "Legendary":
        word = get_word(WORDS_LEGENDARY)
        if word: reasons = ["⭐ 5 букв", "🚫 Без цифр", "✅ Редкий корень"]
    
    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary"] and not word:
        # Если все слова этой редкости заняты — понижаем до Epic
        rarity = "Epic"
        picked = RARITIES[3]

    if rarity == "Epic":
        word = random.choice(WORDS_EPIC)
        tag = f"@{word}_{random.randint(1,99)}"
        reasons = ["✅ Короткое читаемое слово", "✅ Легко запомнить"]
    elif rarity == "Rare":
        word = random.choice(WORDS_RARE)
        tag = f"@{word}_{random.randint(100,999)}"
        reasons = ["✅ Без нижнего подчеркивания", "✅ Звучный корень"]
    elif rarity == "Uncommon":
        word = random.choice(WORDS_UNCOMMON)
        tag = f"@{word}{random.randint(1000,9999)}"
        reasons = ["✅ Красивый числовой суффикс"]
    elif rarity == "Common":
        word = random.choice(["user", "bot", "acc", "id"])
        tag = f"@{word}_{random.randint(10000,99999)}"
        reasons = ["Обычный тег с цифрами"]
    else:
        tag = f"@{word}"

    return tag, rarity, picked["inc"], picked["xp"], picked["sell"], ",".join(reasons)


# ==========================================
# 3. API МОДЕЛИ
# ==========================================
class LoginReq(BaseModel):
    user_id: int
    username: str = "Player"
    ref_by: str = ""

class MintReq(BaseModel):
    user_id: int
    mode: str = "basic"
    spin_count: int = 1

class SellReq(BaseModel):
    user_id: int
    tag: str

class UpgradeReq(BaseModel):
    user_id: int
    mgr_type: str  # 'smm' или 'buyer'

# ==========================================
# 4. РОУТЫ (ENDPOINTS)
# ==========================================
@app.get("/")
def serve_index():
    if os.path.exists("index.html"): return FileResponse("index.html")
    return HTMLResponse("<h2>index.html не найден</h2>", status_code=404)

@app.post("/api/login")
def login(data: LoginReq):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = int(time.time())
    
    cur.execute("SELECT balance, level, xp, refs_count FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    
    if not row:
        ref_id = None
        if data.ref_by and data.ref_by.startswith("ref_"):
            try:
                ref_id = int(data.ref_by.split("_")[1])
                # Проверка, что рефовод существует
                cur.execute("SELECT refs_count FROM users WHERE tg_user_id = ?", (ref_id,))
                ref_user = cur.fetchone()
                if ref_user and ref_id != data.user_id:
                    new_refs = ref_user[0] + 1
                    reward = 1000
                    if new_refs == 2: reward = 3000
                    elif new_refs == 5: reward = 10000
                    elif new_refs == 20: reward = 1000000
                    # Начисляем награду рефоводу
                    cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (new_refs, reward, ref_id))
            except:
                pass
                
        cur.execute(
            "INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, created_at, last_claim) VALUES (?, ?, 1500.0, 1, 0, ?, ?, ?)",
            (data.user_id, data.username, ref_id, now, now)
        )
        conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/state/{user_id}")
def get_state(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT balance, level, xp, smm_lvl, buyer_lvl, luck_until FROM users WHERE tg_user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    balance, level, xp, smm, buyer, luck_until = user
    now = int(time.time())
    
    cur.execute("SELECT tag, rarity, income_per_sec, sell_price, reasons, is_equipped FROM usernames WHERE owner_id = ? ORDER BY income_per_sec DESC", (user_id,))
    tags = []
    equipped_tag = "@Не привязан"
    for r in cur.fetchall():
        tags.append({"tag": r[0], "rarity": r[1], "income": r[2], "sell": r[3], "reasons": r[4].split(",")})
        if r[5] == 1: equipped_tag = r[0]
        
    conn.close()
    return {
        "balance": round(balance, 2),
        "level": level,
        "xp": xp,
        "smm": smm,
        "buyer": buyer,
        "luck_active": luck_until > now,
        "equipped": equipped_tag,
        "hold": tags
    }

@app.post("/api/mint")
def mint(data: MintReq):
    if data.mode not in SPIN_MODES: raise HTTPException(status_code=400, detail="Invalid mode")
    if data.spin_count not in [1, 5]: raise HTTPException(status_code=400, detail="Invalid spin count")
    
    cost = SPIN_MODES[data.mode]["cost"] * data.spin_count
    now = int(time.time())
    
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute("SELECT balance, level, xp, luck_multi, luck_until FROM users WHERE tg_user_id = ?", (data.user_id,))
    user = cur.fetchone()
    if not user or user[0] < cost:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно GRAM!")
        
    # Проверка лимита Холда
    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ?", (data.user_id,))
    if cur.fetchone()[0] + data.spin_count > 100:
        conn.close()
        raise HTTPException(status_code=400, detail="ХОЛД переполнен! Максимум 100 тегов.")
        
    balance, level, xp, luck_multi, luck_until = user
    active_luck = luck_multi if luck_until > now else 1.0
    
    drops = []
    total_xp_gain = 0
    
    for _ in range(data.spin_count):
        for _ in range(10): # Защита от дубликатов
            tag, rarity, inc, xp_g, sell, reasons = generate_tag_logic(cur, data.mode, active_luck)
            cur.execute("SELECT tag FROM usernames WHERE tag = ?", (tag,))
            if not cur.fetchone(): break
        else:
            tag, rarity, inc, xp_g, sell, reasons = f"@user_{random.randint(10000,99999)}", "Common", 1.0, 5, 50, "Обычный тег"
            
        cur.execute("INSERT INTO usernames (tag, owner_id, rarity, income_per_sec, sell_price, reasons, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tag, data.user_id, rarity, inc, sell, reasons, now))
        drops.append({"tag": tag, "rarity": rarity, "inc": inc, "xp": xp_g, "sell": sell, "reasons": reasons.split(",")})
        total_xp_gain += xp_g
        
    new_balance = balance - cost
    new_xp = xp + total_xp_gain
    new_level = level
    while new_xp >= new_level * 150:
        new_xp -= new_level * 150
        new_level += 1
        
    cur.execute("UPDATE users SET balance = ?, level = ?, xp = ? WHERE tg_user_id = ?", (new_balance, new_level, new_xp, data.user_id))
    conn.commit()
    conn.close()
    
    return {"drops": drops, "new_balance": round(new_balance, 2), "level": new_level, "xp": new_xp}

@app.post("/api/sell")
def sell_tag(data: SellReq):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT sell_price, is_equipped FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="Тег не найден")
        
    if row[1] == 1:
        conn.close()
        raise HTTPException(status_code=400, detail="Нельзя продать привязанный канал! Сначала отвяжи.")
        
    price = row[0]
    cur.execute("DELETE FROM usernames WHERE tag = ?", (data.tag,))
    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (price, data.user_id))
    conn.commit()
    conn.close()
    return {"sold_for": price}

# ==========================================
# 5. МАГАЗИН И STARS (INVOICES)
# ==========================================
PRICES = {
    "luck_x2_1h": {"title": "🍀 Удача x2 (1 час)", "price": 19},
    "luck_x3_2h": {"title": "🔥 Удача x3 (2 часа)", "price": 39},
    "coins_50k":  {"title": "🪙 50,000 GRAM", "price": 15},
    "coins_200k": {"title": "💰 200,000 GRAM", "price": 49},
    "vip_30d":    {"title": "👑 VIP Статус", "price": 89},
}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product: raise HTTPException(status_code=400, detail="Товар не найден")
    link = await bot.create_invoice_link(
        title=product["title"],
        description="Покупка в MintTags: Media Empire",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}
