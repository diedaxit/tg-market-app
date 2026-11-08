import sqlite3
import psycopg2
from psycopg2 import pool
import asyncio
import random
import time
import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from bot import bot, APP_URL

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_NAME = "market.db"
NEWS_CHANNEL = "@MintTags_News"

# СПИСОК ГЛАВНЫХ РАЗРАБОТЧИКОВ (ПОЛНЫЙ ДОСТУП К АДМИНКЕ В НАСТРОЙКАХ)
ADMIN_USERNAMES = {"hatebeinsober21"}
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()}

PG_POOL = None
if DATABASE_URL:
    try:
        PG_POOL = psycopg2.pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
    except Exception:
        PG_POOL = None

class CursorWrapper:
    def __init__(self, raw_cur, is_pg: bool):
        self.cur = raw_cur
        self.is_pg = is_pg

    def execute(self, sql: str, params: tuple | list = ()):
        if self.is_pg:
            q = sql.replace("?", "%s")
            q = q.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "INSERT INTO clans" in q and "ON CONFLICT" not in q:
                q += " ON CONFLICT (clan_id) DO NOTHING"
            if "INSERT INTO usernames" in sql and "OR IGNORE" in sql and "ON CONFLICT" not in q:
                q += " ON CONFLICT (tag) DO NOTHING"
            if "INSERT OR REPLACE INTO usernames" in q:
                q = q.replace("INSERT OR REPLACE INTO usernames", "INSERT INTO usernames")
                q += """ ON CONFLICT (tag) DO UPDATE SET
                    owner_id = EXCLUDED.owner_id, rarity = EXCLUDED.rarity, quality_pct = EXCLUDED.quality_pct,
                    income_per_sec = EXCLUDED.income_per_sec, sell_price = EXCLUDED.sell_price,
                    num_multi = EXCLUDED.num_multi, reasons = EXCLUDED.reasons, is_equipped = EXCLUDED.is_equipped,
                    channel_slot = EXCLUDED.channel_slot, is_saved = EXCLUDED.is_saved, on_market = EXCLUDED.on_market,
                    equipped_at = EXCLUDED.equipped_at, subs_count = EXCLUDED.subs_count"""
            return self.cur.execute(q, params)
        return self.cur.execute(sql, params)

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

class ConnWrapper:
    def __init__(self, raw_conn, is_pg: bool, from_pool: bool = False):
        self.conn = raw_conn
        self.is_pg = is_pg
        self.from_pool = from_pool

    def cursor(self):
        return CursorWrapper(self.conn.cursor(), self.is_pg)

    def commit(self):
        self.conn.commit()

    def close(self):
        if self.is_pg and self.from_pool and PG_POOL:
            try:
                PG_POOL.putconn(self.conn)
                return
            except Exception:
                pass
        try:
            self.conn.close()
        except Exception:
            pass

def get_db():
    global PG_POOL
    if DATABASE_URL:
        if PG_POOL:
            try:
                c = PG_POOL.getconn()
                if c.closed != 0:
                    PG_POOL.putconn(c, close=True)
                    c = psycopg2.connect(DATABASE_URL)
                    return ConnWrapper(c, True, False)
                return ConnWrapper(c, True, True)
            except Exception:
                pass
        raw = psycopg2.connect(DATABASE_URL)
        return ConnWrapper(raw, True, False)
    raw = sqlite3.connect(DB_NAME, timeout=15.0)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA synchronous=NORMAL")
    return ConnWrapper(raw, False, False)

# ==========================================
# ЧЕСТНАЯ ВОЛАТИЛЬНАЯ ЭКОНОМИКА (БЕЗ ГАРАНТИРОВАННОГО ОКУПА 90%, КАЧЕЛИ 0.45x - 1.65x + ПРОК ТИРА ВЫШЕ)
# ==========================================
BASE_PRICE_GRAM = 50.0
DIVINE_SERVER_LIMIT = 75
MAX_PASSIVE_PER_SEC = 2000000.0  # Потолок поднят с 350К до 2,000,000 G/с для эндгейма!
VIP_STYLE_COST_GRAM = 50000000.0

RARITIES = [
    {"name": "Common",       "ru": "Обычный",      "w": 780000, "u_min": 260,       "u_max": 980,        "n_min": 20000,      "n_max": 72000,      "gift_base": 3500,      "inc": 5.0,    "xp": 5,     "num_x": 1.5},
    {"name": "Uncommon",     "ru": "Необычный",    "w": 155000, "u_min": 950,       "u_max": 3600,       "n_min": 65000,      "n_max": 230000,     "gift_base": 8500,      "inc": 15.0,   "xp": 15,    "num_x": 2.5},
    {"name": "Rare",         "ru": "Редкий",       "w": 42000,  "u_min": 3800,      "u_max": 14000,      "n_min": 210000,     "n_max": 740000,     "gift_base": 22000,     "inc": 45.0,   "xp": 40,    "num_x": 5.0},
    {"name": "Epic",         "ru": "Эпический",    "w": 11000,  "u_min": 16000,     "u_max": 58000,      "n_min": 820000,     "n_max": 2950000,    "gift_base": 65000,     "inc": 120.0,  "xp": 100,   "num_x": 10.0},
    {"name": "Legendary",    "ru": "Легендарный",  "w": 2400,   "u_min": 72000,     "u_max": 265000,     "n_min": 3400000,    "n_max": 12500000,   "gift_base": 210000,    "inc": 310.0,  "xp": 300,   "num_x": 20.0},
    {"name": "Mythic",       "ru": "Мифический",   "w": 520,    "u_min": 340000,    "u_max": 1250000,    "n_min": 14500000,   "n_max": 52000000,   "gift_base": 750000,    "inc": 720.0,  "xp": 800,   "num_x": 35.0},
    {"name": "Luxury",       "ru": "Роскошный",    "w": 130,    "u_min": 1600000,   "u_max": 5800000,    "n_min": 56000000,   "n_max": 195000000,  "gift_base": 2900000,   "inc": 1450.0, "xp": 1500,  "num_x": 50.0},
    {"name": "Ultra-Mythic", "ru": "Ультра-Мифик", "w": 35,     "u_min": 9500000,   "u_max": 34000000,   "n_min": 250000000,  "n_max": 780000000,  "gift_base": 14000000,  "inc": 2600.0, "xp": 2500,  "num_x": 65.0},
    {"name": "Exclusive",    "ru": "Эксклюзивный", "w": 10,     "u_min": 48000000,  "u_max": 165000000,  "n_min": 950000000,  "n_max": 2600000000, "gift_base": 60000000,  "inc": 4500.0, "xp": 5000,  "num_x": 80.0},
    {"name": "Divine",       "ru": "Божественный", "w": 2,      "u_min": 240000000, "u_max": 1200000000, "n_min": 3100000000, "n_max": 9200000000, "gift_base": 260000000, "inc": 8500.0, "xp": 15000, "num_x": 95.0}
]

SPIN_TIERS = {
    "tier_0": {"min_idx": 0, "u_cost": 600,      "n_cost": 45000,     "title": "Обычный+"},
    "tier_1": {"min_idx": 1, "u_cost": 2200,     "n_cost": 140000,    "title": "Необычный+"},
    "tier_2": {"min_idx": 2, "u_cost": 8500,     "n_cost": 450000,    "title": "Редкий+"},
    "tier_3": {"min_idx": 3, "u_cost": 35000,    "n_cost": 1800000,   "title": "Эпический+"},
    "tier_4": {"min_idx": 4, "u_cost": 160000,   "n_cost": 7500000,   "title": "Легендарный+"},
    "tier_5": {"min_idx": 5, "u_cost": 750000,   "n_cost": 32000000,  "title": "Мифический+"},
    "tier_6": {"min_idx": 6, "u_cost": 3500000,  "n_cost": 120000000, "title": "Luxury+"}
}

COUNTRIES = {
    "RU": {"name": "Россия",     "flag": "🇷🇺", "prefix": "+7 9"},
    "UA": {"name": "Украина",    "flag": "🇺🇦", "prefix": "+380 9"},
    "BY": {"name": "Беларусь",   "flag": "🇧🇾", "prefix": "+375 29"},
    "KZ": {"name": "Казахстан",  "flag": "🇰🇿", "prefix": "+7 70"},
    "UZ": {"name": "Узбекистан", "flag": "🇺🇿", "prefix": "+998 90"},
    "US": {"name": "США",        "flag": "🇺🇸", "prefix": "+1 305"},
    "AE": {"name": "ОАЭ (Дубай)","flag": "🇦🇪", "prefix": "+971 50"},
    "CN": {"name": "Китай",      "flag": "🇨🇳", "prefix": "+86 13"}
}

def generate_national_phone(country_code: str) -> str:
    c = COUNTRIES.get(country_code, COUNTRIES["RU"])
    pref = c["prefix"]
    if random.random() < 0.04:
        d = random.choice(["7", "8", "9", "0", "5"])
        return f"{pref}{d}{d} {d}{d}{d} {d}{random.randint(10,99)}"
    return f"{pref}{random.randint(10,99)} {random.randint(100,999)} {random.randint(10,99)}{random.randint(10,99)}"

# ==========================================
# МАССОВЫЙ ПУЛ ЖИВЫХ НИКОВ СНГ/МИРА (БЕЗ ТУПЫХ GOLD_23231 И TON3!)
# ==========================================
WORDS = {
    "Divine": [
        "durov", "elon_musk", "telegram", "ton", "gram", "fragment", "bitcoin", "tether", "notcoin", "pavel",
        "apple", "google", "meta", "tesla", "vitalik", "satoshi", "binance", "blackrock", "forbes", "rolex",
        "bugatti", "ferrari", "dubai", "monaco", "trillion", "genesis", "founder", "emperor", "absolute", "immortal",
        "dollar", "crypto", "wallet", "market", "exchange", "diamond", "platinum", "olympus", "paradise", "infinity",
        "qatar", "riyadh", "london", "manhattan", "wallstreet", "nasdaq", "openai", "nvidia", "amazon", "microsoft",
        "youtube", "tiktok", "instagram", "whatsapp", "discord", "twitch", "netflix", "spotify", "playstation", " gta6",
        "madrid", "barcelona", "ronaldo", "messi", "mbappe", "ufc", "champion", "goat", "legendary", "supreme"
    ],
    "Exclusive": [
        "x", "v", "z", "a", "k", "m", "s", "r", "d", "t", "b", "n", "p", "g", "w", "f", "l", "c", "j", "y",
        "ai", "go", "io", "ok", "up", "id", "on", "tv", "me", "we", "oz", "vk", "fx", "hq", "gg", "qq", "xx", "zz",
        "777", "888", "999", "000", "111", "666", "001", "007", "100", "500"
    ],
    "Ultra-Mythic": [
        "news", "auto", "bank", "avia", "chat", "king", "fifa", "game", "sber", "frog", "cat", "dog", "nft", "god",
        "ceo", "vip", "dex", "jet", "pay", "bet", "win", "pro", "top", "lux", "oil", "gas", "art", "law", "med",
        "red", "sky", "sun", "ice", "zen", "neo", "max", "leo", "eva", "mia", "ray", "ash", "fox", "owl", "ape"
    ],
    "Luxury": [
        "litvin", "mellstroy", "mrbeast", "hasbulla", "morgen", "buster", "bratishkin", "zubarev", "exile", "koresh",
        "paradeev1ch", "frame_tamer", "kuplinov", "wylsacom", "bigebabytape", "kizaru", "og_buda", "mayot", "soda_luv",
        "pharaoh", "scriptonite", "macan", "miyagi", "asta", "dava", "instasamka", "gensyxa", "tenderlybae", "karna_val",
        "cartier", "lambo", "porsche", "maybach", "brabus", "g_wagon", "patek", "richard_mille", "balenciaga", "gucci",
        "prada", "lv", "hermes", "dior", "chanel", "versace", "bentley", "rolls_royce", "aston_martin", "mclaren"
    ],
    "Mythic": [
        "whale", "tiger", "ghost", "alpha", "prime", "snake", "eagle", "crown", "royal", "pearl", "laser", "cyber",
        "orbit", "solar", "venom", "strix", "demon", "angel", "reaper", "warden", "shogun", "kaiser", "tycoon", "baron",
        "oracle", "mirage", "nebula", "cosmos", "pulsar", "quasar", "zenith", "apex", "sigma", "omen", "havoc", "chaos"
    ],
    "Legendary": [
        "daner", "avusk", "leoon", "dragon", "knight", "sultan", "legend", "empire", "falcon", "vector", "matrix",
        "vortex", "shadow", "spirit", "phoenix", "titan", "viking", "samurai", "ronin", "spartan", "gladiator", "paladin",
        "crusader", "berserk", "valkyrie", "griffin", "hydra", "kraken", "leviathan", "cerberus", "pegasus", "chimera"
    ],
    "Epic": [
        "sniper", "hacker", "phantom", "ninja", "blade", "broker", "dealer", "magnet", "stalker", "raider", "hunter",
        "outlaw", "bandit", "pirate", "corsair", "nomad", "ranger", "scout", "wizard", "warlock", "sorcerer", "alchemist"
    ]
}

REAL_CHAT_USERNAMES = [
    "kach1k", "vdbv01", "bambrel", "tryyxissss", "Mr_MaDaRaMyS_Gay", "bigebabytape", "VaItrex", "Kloneex",
    "ProjectinappleSon", "pcixanyl", "BususVlad", "akatuman", "wuruw", "saphiressss", "bot_starry", "rysofobs",
    "fckasscunt", "eyeallaha", "chatchitai", "notsnitch", "pirogovstepa", "imfuckinggirl", "feodulov", "dealersex",
    "kynuluv", "raqking", "valdberiz", "prikidy", "rekomendoval", "hatebeinsober21", "zxcursed", "shadowraze",
    "dota_rep", "dead_inside", "tokyo_ghoul", "lovv66", "bushido_zho", "heronwater", "seeyaside", "uglystephan",
    "scally_milano", "163onmyneck", "platina300", "obladaet", "markul", "thomas_mraz", "yanix", "lsp_official",
    "slava_marlow", "eldzhey", "feduk_one", "oxxxymiron", "noize_mc", "kasta_ru", "basta_aka", "guf_zm",
    "centr_msk", "smoki_mo", "rem_digga", "miyagi_black", "endshpil", "truwer", "niki_l", "captown",
    "kairat_nurtas", "jah_khalib", "scripto_kz", "limba_music", "jony_baku", "andro_dragon", "el_man", "rauf_faik",
    "hammali", "navai_bro", "macan_77", "xcho_official", "jakone", "avg_music", "inst_rina", "egor_kreed",
    "timati_black", "mot_23", "klava_koka", "niletto", "zivert_fly", "anna_asti", "artik_self", "loli_lips",
    "twinky_boy", "venom_zxc", "kaneki_ken", "itachi_uchiha", "sasuke_kun", "naruto_uzumaki", "gojo_satoru",
    "sukuna_ryomen", "eren_yeager", "levi_ackerman", "mikasa_s", "makima_chainsaw", "denji_dog", "power_blood",
    "guts_berserk", "griffith_hawk", "light_yagami", "ryuk_apple", "l_lawliet", "lelouch_vi", "jotaro_kujo",
    "dio_brando", "giorno_giovanna", "hisoka_morow", "killua_zoldyck", "gon_freecss", "kurapika_eyes", "chrollo_lucilfer"
]

def generate_live_human_username(rarity_name: str) -> str:
    base = random.choice(REAL_CHAT_USERNAMES)
    if rarity_name == "Rare":
        return f"@{base}"
    elif rarity_name == "Uncommon":
        if random.random() < 0.55:
            return f"@{base}"
        return f"@{base}_{random.choice(['x', 'v', 'z', 'pro', 'tg', '01', '77', '99'])}"
    else:
        if random.random() < 0.35:
            return f"@{base}"
        return f"@{base}{random.randint(10, 999)}"

GIFT_CATALOG = {
    "Common":       [("Леденец TON", 1.0, "lollipop"), ("Кофе Разработчика", 1.1, "coffee"), ("Шарик Telegram", 1.2, "balloon")],
    "Uncommon":     [("Алая Роза", 1.0, "rose"), ("Торт Дурова", 1.15, "cake"), ("Шампанское Магната", 1.25, "champagne")],
    "Rare":         [("UFC Strike", 1.0, "glove"), ("Цилиндр Джентльмена", 1.1, "hat"), ("Магический Шар", 1.25, "orb")],
    "Epic":         [("Scared Cat", 1.0, "cat"), ("Heart Locket N.Y.C.", 1.15, "locket"), ("Swiss Watch", 1.35, "watch")],
    "Legendary":    [("Heroic Helmet", 1.0, "helmet"), ("Durov's Cap", 1.2, "cap"), ("Синий Plush Pepe", 1.4, "pepe_blue")],
    "Mythic":       [("Resistance Dog (REDO)", 1.0, "redo"), ("Красный Plush Pepe", 1.25, "pepe_red"), ("Розовый Plush Pepe", 1.4, "pepe_pink")],
    "Luxury":       [("Фиолетовый Plush Pepe", 1.0, "pepe_purple"), ("Изумрудный Plush Pepe", 1.3, "pepe_emerald"), ("Спорткар Магната", 1.15, "car")],
    "Ultra-Mythic": [("Золотой Plush Pepe", 1.35, "pepe_gold"), ("Корона Основателя", 1.15, "crown"), ("Яхта Шейха Дубая", 1.1, "yacht")],
    "Exclusive":    [("Космо-Галактический Pepe", 1.4, "pepe_cosmic"), ("Золотой REDO", 1.25, "redo_gold"), ("Остров в Дубае", 1.1, "island")],
    "Divine":       [("Genesis Gold Plush Pepe", 1.5, "pepe_genesis"), ("Genesis REDO", 1.35, "redo_genesis"), ("Ключ Блокчейна TON", 1.25, "key_ton")]
}

# ==========================================
# БОКСЫ И КЕЙСЫ (С ALL-IN ЗА 10K G И ПОВЫШЕННЫМ ОКУПОМ ДОНАТНЫХ БОКСОВ!)
# ==========================================
CASES_CATALOG = {
    "case_all_in": {
        "title": "ALL-IN БОКС (ВСЁ ИЛИ НИЧЕГО)",
        "sub": "99.89% Обычный мусор • 0.111% Божественный или Эксклюзив!",
        "curr": "gram", "price": 10000, "types": ["username", "number", "gift"],
        "weights": {0: 99889, 8: 80, 9: 31}
    },
    "case_tag_start": {
        "title": "Стартовый Tag-Бокс", "sub": "Только @username (Uncommon ➔ Legendary)",
        "curr": "gram", "price": 6500, "types": ["username"],
        "weights": {1: 580, 2: 330, 3: 80, 4: 10}
    },
    "case_gifts_ton": {
        "title": "Gift-Бокс: Пепе и Часы", "sub": "NFT-Подарки (Черный фон Blackout = ×10 к цене!)",
        "curr": "gram", "price": 48000, "types": ["gift"],
        "weights": {2: 520, 3: 330, 4: 115, 5: 30, 6: 5}
    },
    "case_num_888": {
        "title": "Бокс Анонимных +888", "sub": "Только дорогие номера +888 для каналов",
        "curr": "gram", "price": 220000, "types": ["number"],
        "weights": {1: 480, 2: 350, 3: 130, 4: 35, 5: 5}
    },
    "case_sheikh_mix": {
        "title": "Бокс Шейха (Микс 3-в-1)", "sub": "@username + Номера +888 + NFT-Подарки (Rare+)",
        "curr": "gram", "price": 290000, "types": ["username", "number", "gift"],
        "weights": {2: 380, 3: 380, 4: 170, 5: 55, 6: 12, 7: 3}
    },
    "case_oligarch": {
        "title": "Олигарх Контейнер", "sub": "Тяжелый люкс: гарантия Legendary и выше!",
        "curr": "gram", "price": 1800000, "types": ["username", "number", "gift"],
        "weights": {4: 520, 5: 320, 6: 120, 7: 32, 8: 6, 9: 2}
    },
    "case_stars_lite": {
        "title": "Звездный Ларец", "sub": "Усиленный окуп ×1.45: Legendary+ и шанс на Divine Pepe!",
        "curr": "stars", "price": 29, "types": ["username", "gift"],
        "weights": {4: 500, 5: 320, 6: 130, 7: 38, 8: 10, 9: 2}
    },
    "case_stars_founder": {
        "title": "Бокс Основателя", "sub": "Усиленный окуп ×1.55: Luxury+ (+888, Топ-Ник, Blackout Pepe)",
        "curr": "stars", "price": 99, "types": ["username", "number", "gift"],
        "weights": {5: 380, 6: 390, 7: 165, 8: 50, 9: 15}
    },
    "case_stars_divine": {
        "title": "Божественный Сундук Дурова", "sub": "Усиленный окуп ×1.75: Ultra-Mythic, Exclusive и Divine!",
        "curr": "stars", "price": 249, "types": ["username", "number", "gift"],
        "weights": {6: 260, 7: 420, 8: 230, 9: 90}
    }
}

def init_db():
    conn = get_db()
    cur = conn.cursor()
    id_type = "SERIAL PRIMARY KEY" if conn.is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    big_type = "BIGINT" if conn.is_pg else "INTEGER"

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            member_number {id_type},
            tg_user_id {big_type} UNIQUE,
            username TEXT,
            balance REAL DEFAULT 15000.0,
            stars_balance INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            season_xp INTEGER DEFAULT 0,
            season_claimed TEXT DEFAULT '[]',
            luck_multi REAL DEFAULT 1.0,
            luck_until {big_type} DEFAULT 0,
            vip_until {big_type} DEFAULT 0,
            max_hold INTEGER DEFAULT 100,
            max_channels INTEGER DEFAULT 2,
            ref_by {big_type} DEFAULT NULL,
            refs_count INTEGER DEFAULT 0,
            ref_3_rewarded INTEGER DEFAULT 0,
            contrib_gram REAL DEFAULT 0.0,
            contrib_stars INTEGER DEFAULT 0,
            smm_lvl INTEGER DEFAULT 1,
            buyer_lvl INTEGER DEFAULT 0,
            ai_boost INTEGER DEFAULT 0,
            clan_id TEXT DEFAULT NULL,
            clan_contrib REAL DEFAULT 0.0,
            total_spins INTEGER DEFAULT 0,
            pity_100 INTEGER DEFAULT 0,
            pity_500 INTEGER DEFAULT 0,
            last_wheel {big_type} DEFAULT 0,
            last_vault {big_type} DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily {big_type} DEFAULT 0,
            q_spins INTEGER DEFAULT 0,
            q_rare INTEGER DEFAULT 0,
            q_crafts INTEGER DEFAULT 0,
            q_duels INTEGER DEFAULT 0,
            q_claimed TEXT DEFAULT '[]',
            w_spins INTEGER DEFAULT 0,
            w_cases INTEGER DEFAULT 0,
            w_duels INTEGER DEFAULT 0,
            w_claimed TEXT DEFAULT '[]',
            ach_stats TEXT DEFAULT '{{}}',
            ach_claimed TEXT DEFAULT '[]',
            albums_claimed TEXT DEFAULT '[]',
            promos_used TEXT DEFAULT '[]',
            contracts_done TEXT DEFAULT '[]',
            tax_shield_until {big_type} DEFAULT 0,
            tax_raid_amount REAL DEFAULT 0.0,
            tax_raid_deadline {big_type} DEFAULT 0,
            duel_wins INTEGER DEFAULT 0,
            auto_save_min_idx INTEGER DEFAULT 0,
            sub_verified INTEGER DEFAULT 0,
            notify_merchant INTEGER DEFAULT 0,
            gears INTEGER DEFAULT 0,
            repair_kits INTEGER DEFAULT 0,
            lockpicks INTEGER DEFAULT 0,
            museum_tags TEXT DEFAULT '[]',
            museum_likes INTEGER DEFAULT 0,
            liked_users TEXT DEFAULT '[]',
            lottery_tickets INTEGER DEFAULT 0,
            nick_color TEXT DEFAULT '#f8fafc',
            custom_title TEXT DEFAULT 'Магнат',
            profile_frame TEXT DEFAULT 'default',
            unlocked_titles TEXT DEFAULT '["Магнат"]',
            country_code TEXT DEFAULT '',
            national_phone TEXT DEFAULT '',
            masked_by_nft TEXT DEFAULT '',
            last_story_at {big_type} DEFAULT 0,
            last_claim {big_type} DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS usernames (
            tag TEXT PRIMARY KEY,
            item_type TEXT DEFAULT 'username',
            owner_id {big_type},
            rarity TEXT,
            quality_pct INTEGER DEFAULT 95,
            income_per_sec REAL,
            sell_price REAL,
            num_multi REAL DEFAULT 1.0,
            reasons TEXT,
            is_equipped INTEGER DEFAULT 0,
            channel_slot INTEGER DEFAULT 0,
            is_saved INTEGER DEFAULT 1,
            on_market INTEGER DEFAULT 0,
            is_staked INTEGER DEFAULT 0,
            is_verified INTEGER DEFAULT 0,
            last_duel_at {big_type} DEFAULT 0,
            equipped_at {big_type} DEFAULT 0,
            subs_count INTEGER DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS staked_deposits (
            stake_id {id_type},
            user_id {big_type},
            stake_type TEXT,
            tag TEXT DEFAULT '',
            principal_gram REAL DEFAULT 0.0,
            reward_gram REAL DEFAULT 0.0,
            hours INTEGER DEFAULT 3,
            unlocks_at {big_type},
            claimed INTEGER DEFAULT 0,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS gift_checks (
            code TEXT PRIMARY KEY,
            creator_id {big_type},
            amount REAL,
            claimed_by {big_type} DEFAULT NULL,
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS market_lots (
            lot_id {id_type},
            tag TEXT UNIQUE,
            item_type TEXT,
            rarity TEXT,
            income_per_sec REAL,
            num_multi REAL DEFAULT 1.0,
            reasons TEXT,
            seller_id {big_type},
            seller_name TEXT,
            currency TEXT DEFAULT 'gram',
            is_auction INTEGER DEFAULT 0,
            start_price REAL,
            current_price REAL,
            buyout_price REAL,
            highest_bidder_id {big_type} DEFAULT NULL,
            highest_bidder_name TEXT DEFAULT '',
            bids_count INTEGER DEFAULT 0,
            ends_at {big_type},
            created_at {big_type}
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS clans (
            clan_id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            owner_id {big_type} DEFAULT 0,
            level INTEGER DEFAULT 1,
            treasury REAL DEFAULT 0.0,
            members_count INTEGER DEFAULT 0,
            max_members INTEGER DEFAULT 100,
            created_at {big_type} DEFAULT 0
        )
    """)
    conn.commit()

    new_user_cols = [
        ("stars_balance", "INTEGER DEFAULT 0"),
        ("w_spins", "INTEGER DEFAULT 0"),
        ("w_cases", "INTEGER DEFAULT 0"),
        ("w_duels", "INTEGER DEFAULT 0"),
        ("w_claimed", "TEXT DEFAULT '[]'"),
        ("tax_raid_amount", "REAL DEFAULT 0.0"),
        ("tax_raid_deadline", f"{big_type} DEFAULT 0"),
        ("unlocked_titles", "TEXT DEFAULT '[\"Магнат\"]'"),
        ("country_code", "TEXT DEFAULT ''"),
        ("national_phone", "TEXT DEFAULT ''"),
        ("masked_by_nft", "TEXT DEFAULT ''"),
        ("last_story_at", f"{big_type} DEFAULT 0")
    ]
    for col, ctype in new_user_cols:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ctype}" if conn.is_pg else f"ALTER TABLE users ADD COLUMN {col} {ctype}")
            conn.commit()
        except Exception:
            if conn.is_pg: conn.conn.rollback()

    for col, ctype in [
        ("equipped_at", f"{big_type} DEFAULT 0"),
        ("subs_count", "INTEGER DEFAULT 0")
    ]:
        try:
            cur.execute(f"ALTER TABLE usernames ADD COLUMN IF NOT EXISTS {col} {ctype}" if conn.is_pg else f"ALTER TABLE usernames ADD COLUMN {col} {ctype}")
            conn.commit()
        except Exception:
            if conn.is_pg: conn.conn.rollback()

    try:
        cur.execute("ALTER TABLE market_lots ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'gram'" if conn.is_pg else "ALTER TABLE market_lots ADD COLUMN currency TEXT DEFAULT 'gram'")
        conn.commit()
    except Exception:
        if conn.is_pg: conn.conn.rollback()

    # Фикс бага с качеством > 100% и старых кривых суффиксов TON3 / GOLD5
    try:
        cur.execute("UPDATE usernames SET quality_pct = 100 WHERE quality_pct > 100")
        conn.commit()
    except Exception:
        if conn.is_pg: conn.conn.rollback()

    cur.execute("""
        INSERT OR IGNORE INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at)
        VALUES ('mint_general', 'MintGeneral', 0, 5, 1000000.0, 1, 1000, ?)
    """, (int(time.time()),))
    conn.commit()
    conn.close()

init_db()

RATE_BUCKETS = {}
TX_LOCKS = set()
ACTIVE_ROCKETS = {}
ACTIVE_MINES = {}
LOTTERY_STATE = {"pot": 1500000.0, "last_winner": "@durov", "last_win_amount": 4250000.0}

def is_user_admin(uid: int, uname: str = "") -> bool:
    clean = (uname or "").strip().lower().replace("@", "")
    return (uid in ADMIN_IDS) or (clean in ADMIN_USERNAMES)

def check_rate(uid: int, max_hits: int = 22, window: float = 2.0):
    now = time.time()
    arr = [t for t in RATE_BUCKETS.get(uid, []) if now - t < window]
    if len(arr) >= max_hits:
        raise HTTPException(429, "Слишком быстро! Подождите секунду.")
    arr.append(now)
    RATE_BUCKETS[uid] = arr

MAX_SMM_LVL = 25
MAX_BUYER_LVL = 20

def get_smm_upgrade_cost(lvl: int) -> float:
    return round(6000.0 * (2.25 ** (lvl - 1)))

def get_buyer_upgrade_cost(lvl: int) -> float:
    return round(35000.0 * (2.45 ** lvl))

def get_pass_level_info(season_xp: int):
    lvl = 0
    rem = max(0, int(season_xp))
    while lvl < 100:
        req = int(40 + (lvl + 1) * 18 + ((lvl + 1) ** 1.45) * 8)
        if rem >= req:
            rem -= req
            lvl += 1
        else:
            return lvl, rem, req
    return 100, 0, 1000

def get_pass_skip_cost_stars(cur_lvl: int) -> int:
    nxt = cur_lvl + 1
    if nxt <= 10: return 3
    if nxt <= 25: return 5
    if nxt <= 50: return 9
    if nxt <= 75: return 15
    if nxt <= 90: return 22
    return 29

def get_pass_reward_for_level(lvl: int):
    if lvl == 100:
        return {"type": "mega_100", "title": "👑 VIP (12ч) + 🔥 Удача ×5 (3ч) + 50M G", "gram": 50000000}
    if lvl == 99:
        return {"type": "blackout_pepe", "title": "🖤 Blackout Plush Pepe (100M – 1B G)", "gram": 0}
    if lvl % 10 == 0:
        return {"type": "stars_and_gram", "title": f"⭐️ +{lvl // 5} Stars и {(lvl * 150000):,} G", "gram": lvl * 150000, "stars": lvl // 5}
    return {"type": "gram", "title": f"{(lvl * 35000):,} GRAM", "gram": lvl * 35000}

def get_daily_hot_series():
    day_seed = int(time.time() // 3600)
    series_list = [
        {"code": "pepe", "title": "Рыночный бум на Plush Pepe!", "bonus_pct": 45},
        {"code": "77",   "title": "Ажиотаж на цифры «77» в номере", "bonus_pct": 40},
        {"code": "888",  "title": "Высокий спрос на все номера +888", "bonus_pct": 35},
        {"code": "watch","title": "Взлет цен на Swiss Watch и Helmet", "bonus_pct": 45},
        {"code": "a",    "title": "Теги, начинающиеся на «@a»", "bonus_pct": 35}
    ]
    return series_list[day_seed % len(series_list)]

def get_daily_vip_contracts():
    day_seed = int(time.time() // 86400)
    return [
        {"id": f"c1_{day_seed}", "title": "Заказ Блогера: Любой Epic @username", "req_type": "username", "req_rar": "Epic", "mult": 2.1, "flat_bonus": 45000},
        {"id": f"c2_{day_seed}", "title": "Заказ Коллекционера: Epic+ NFT-Подарок", "req_type": "gift", "req_rar": "Epic", "mult": 2.3, "flat_bonus": 85000},
        {"id": f"c3_{day_seed}", "title": "Заказ Холдинга: Номер +888 (Rare)", "req_type": "number", "req_rar": "Rare", "mult": 2.0, "flat_bonus": 150000}
    ]

def get_active_merchant_offer():
    now = int(time.time())
    slot_20m = now // 1200
    phase = now % 1200
    offers = [
        {"rarity": "Rare",      "ru": "Редкий",      "bonus_mult": 1.65, "bonus_pct": 65, "title": "Тайный Скупщик охотится за Rare!"},
        {"rarity": "Epic",      "ru": "Эпический",   "bonus_mult": 1.75, "bonus_pct": 75, "title": "Арабский Шейх скупает Epic!"},
        {"rarity": "Uncommon",  "ru": "Необычный",   "bonus_mult": 1.80, "bonus_pct": 80, "title": "Оптовый Байер скупает Uncommon!"},
        {"rarity": "Legendary", "ru": "Легендарный", "bonus_mult": 1.60, "bonus_pct": 60, "title": "Киты TON скупают Legendary!"}
    ]
    pick = dict(offers[slot_20m % len(offers)])
    pick["active"] = phase < 600
    pick["left_sec"] = (600 - phase) if phase < 600 else 0
    pick["next_in_sec"] = 0 if phase < 600 else (1200 - phase)
    pick["slot_id"] = slot_20m
    return pick

# ==========================================
# ГЕНЕРАТОРЫ ПРЕДМЕТОВ (БЕЗ TON3/GOLD5 И С ЖЕСТКИМ КАПОМ КАЧЕСТВА 100%)
# ==========================================
def generate_nft_gift_fragment(r_obj: dict, quality_override: int = None, force_blackout: bool = False):
    rarity_name = r_obj["name"]
    quality = min(100, max(15, quality_override if quality_override is not None else random.randint(76, 100)))
    pool_g = GIFT_CATALOG.get(rarity_name, GIFT_CATALOG["Common"])
    g_title, skin_mult, _ = random.choice(pool_g)

    r_bg = random.random()
    if force_blackout or r_bg < 0.14 or rarity_name in ["Divine", "Exclusive"]:
        bg_mult = 10.0
        bg_label = "Фон «Blackout Onyx» (Чистый Черный)"
        bg_badge = " [BLACKOUT]"
    elif r_bg < 0.42:
        bg_mult = 2.8
        bg_label = "Фон «True Match» (В цвет скина)"
        bg_badge = " [MATCH]"
    else:
        bg_mult = 1.0
        bg_label = "Стандартный узор фона"
        bg_badge = ""

    r_mint = random.random()
    if rarity_name in ["Divine", "Exclusive"] or r_mint < 0.03:
        serial = random.randint(1, 9)
        mint_mult = 2.5
        mint_lbl = f"Элитный минт Топ-10 (#{serial})"
    elif rarity_name in ["Ultra-Mythic", "Luxury"] or r_mint < 0.18:
        serial = random.choice([77, 88, 99, 100, 777, 888, random.randint(10, 99)])
        mint_mult = 1.45
        mint_lbl = f"Коллекционный минт (#{serial})"
    else:
        serial = random.randint(101, 9999)
        mint_mult = 1.0
        mint_lbl = f"Серийный номер (#{serial})"

    tag = f"{g_title} #{serial}{bg_badge}"
    q_mult = round(0.85 + (quality / 100.0) * 0.30, 2)
    base_floor = float(r_obj["gift_base"])
    sell = round(base_floor * skin_mult * bg_mult * mint_mult * q_mult)
    inc = round(r_obj["inc"] * (2.0 if bg_mult >= 10.0 else 1.35) * (quality / 100.0), 2)

    factors = [
        {"label": f"Базовый флор «{g_title}» ({r_obj['ru']})", "mult": f"{int(base_floor * skin_mult):,} G".replace(",", " ")},
        {"label": bg_label, "mult": f"×{bg_mult}".replace(".0", "")},
        {"label": mint_lbl, "mult": f"×{mint_mult}".replace(".", ",")},
        {"label": f"Сохранность ({quality}%)", "mult": f"×{q_mult}".replace(".", ",")}
    ]
    reasons_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)
    return tag, inc, sell, 1.0, quality, reasons_str, factors

def generate_phone_number_fragment(r_obj: dict, quality_override: int = None):
    rarity_name = r_obj["name"]
    num_x = r_obj["num_x"]
    quality = min(100, max(15, quality_override if quality_override is not None else random.randint(76, 100)))

    if rarity_name == "Divine":
        tag = f"+888 8 {random.choice(['888', '777', '000', '999', '111', '666', '555', f'{random.randint(1,9)}00'])}"
        pat_lbl = "Божественный короткий блок +888"
    elif rarity_name == "Exclusive":
        d = random.randint(10, 99)
        tag = random.choice([f"+888 {d}", f"+888 8 {random.randint(100, 999)}"])
        pat_lbl = "Ультра-короткий индекс +888"
    elif rarity_name == "Ultra-Mythic":
        tag = f"+888 8 {random.randint(100, 999)}"
        pat_lbl = "Золотой реестр +888"
    elif rarity_name == "Luxury":
        tag = f"+888 0{random.randint(100, 999)}"
        pat_lbl = "Четырехзначный VIP-блок +888"
    elif rarity_name == "Mythic":
        d = random.choice(["777", "888", "999", "000", "555"])
        tag = f"+888 {random.randint(10, 99)} {d}"
        pat_lbl = f"Триплет «{d}» в номере"
    elif rarity_name == "Legendary":
        tag = f"+888 {random.randint(1,9)}000 {random.randint(10,99)}0"
        pat_lbl = "Тысячная круглая серия «000»"
    elif rarity_name == "Epic":
        a, b = random.randint(1, 9), random.randint(1, 9)
        tag = f"+888 {a}{a}{b}{b} {random.randint(100,999)}"
        pat_lbl = "Двойной парный дубль цифр"
    elif rarity_name == "Rare":
        a = random.randint(10, 99)
        tag = f"+888 {a}{a} {random.randint(100,999)}"
        pat_lbl = "Зеркальная пара цифр"
    elif rarity_name == "Uncommon":
        tag = f"+888 {random.randint(100,999)}0 {random.randint(10,99)}0"
        pat_lbl = "Закрытые нули серии"
    else:
        tag = f"+888 {random.randint(1000,9999)} {random.randint(100,999)}"
        pat_lbl = "Стандартный анонимный пул +888"

    pat_roll = random.uniform(0.0, 1.0)
    q_norm = max(0.0, min(1.0, (quality - 70) / 30.0))
    blend = 0.70 * pat_roll + 0.30 * q_norm
    sell = round(r_obj["n_min"] + (r_obj["n_max"] - r_obj["n_min"]) * blend)
    inc = round(r_obj["inc"] * 1.8 * (quality / 100.0), 2)

    total_mult_50 = max(1, int(sell / BASE_PRICE_GRAM))
    pat_mult_disp = round(0.55 + pat_roll * 1.35, 2)

    factors = [
        {"label": "Базовая ставка Fragment", "mult": "50 G"},
        {"label": f"{pat_lbl} ({r_obj['ru']})", "mult": f"×{total_mult_50:,}".replace(",", " ")},
        {"label": "Волатильность спроса", "mult": f"×{pat_mult_disp}".replace(".", ",")},
        {"label": "Множитель ко всем каналам", "mult": f"×{num_x}"}
    ]
    reasons_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)
    return tag, inc, sell, num_x, quality, reasons_str, factors

def fast_build_item_in_memory(item_type: str, rar_idx: int, luck: float = 1.0, quality_override: int = None, force_blackout: bool = False):
    picked = RARITIES[rar_idx]
    rarity = picked["name"]

    if item_type == "number":
        tag, inc, sell, num_x, qual, reas_str, factors = generate_phone_number_fragment(picked, quality_override)
        return {
            "tag": tag, "type": "number", "rarity": rarity, "rar_idx": rar_idx, "quality": qual,
            "inc": inc, "xp": picked["xp"] * 2, "sell": sell, "num_multi": num_x,
            "reasons": reas_str, "factors": factors
        }

    if item_type == "gift":
        tag, inc, sell, num_x, qual, reas_str, factors = generate_nft_gift_fragment(picked, quality_override, force_blackout)
        return {
            "tag": tag, "type": "gift", "rarity": rarity, "rar_idx": rar_idx, "quality": qual,
            "inc": inc, "xp": picked["xp"] * 2, "sell": sell, "num_multi": num_x,
            "reasons": reas_str, "factors": factors
        }

    quality = min(100, max(15, quality_override if quality_override is not None else random.randint(76, 100)))
    if rarity in ["Divine", "Exclusive", "Ultra-Mythic", "Luxury", "Mythic", "Legendary", "Epic"]:
        base_w = random.choice(WORDS.get(rarity, ["king"])).strip()
        tag = f"@{base_w}"
    else:
        tag = generate_live_human_username(rarity)

    clean = tag.replace("@", "")
    has_digits_or_under = any(c.isdigit() or c == "_" for c in clean)

    word_roll = random.uniform(0.0, 1.0)
    q_norm = max(0.0, min(1.0, (quality - 70) / 30.0))
    blend = 0.72 * word_roll + 0.28 * q_norm
    sell = round(picked["u_min"] + (picked["u_max"] - picked["u_min"]) * blend)
    inc = round(picked["inc"] * (quality / 100.0), 2)

    total_mult_50 = max(1, int(sell / BASE_PRICE_GRAM))
    clean_disp = "×1,5" if not has_digits_or_under else "×0,85"
    q_disp = round(0.85 + q_norm * 0.30, 2)

    factors = [
        {"label": "Базовая оценка тега", "mult": "50 G"},
        {"label": f"Категория «{picked['ru']}» ({tag})", "mult": f"×{total_mult_50:,}".replace(",", " ")},
        {"label": f"Чистые буквы ({len(clean)} симв.)" if not has_digits_or_under else "Живой никнейм чата", "mult": clean_disp},
        {"label": f"Сохранность ({quality}%)", "mult": f"×{q_disp}".replace(".", ",")}
    ]
    reas_str = "|".join(f"{f['label']} {f['mult']}" for f in factors)

    return {
        "tag": tag, "type": "username", "rarity": rarity, "rar_idx": rar_idx, "quality": quality,
        "inc": inc, "xp": picked["xp"], "sell": sell, "num_multi": 1.0,
        "reasons": reas_str, "factors": factors
    }

def roll_single_candidate_fast(cur, item_type: str, tier_key: str, luck: float, user_id: int = 0):
    min_idx = SPIN_TIERS.get(tier_key, SPIN_TIERS["tier_0"])["min_idx"]
    pool_r = []
    total_w = 0
    for i, r in enumerate(RARITIES):
        if i < min_idx:
            continue
        dist = i - min_idx
        decay_weights = [875000, 96000, 20000, 4200, 850, 175, 38, 9, 2, 1]
        base_w = r["w"] if min_idx == 0 else decay_weights[min(dist, len(decay_weights) - 1)]
        effective_luck = 1.0 if dist == 0 else float(max(1.0, luck))
        w = max(1, int(base_w * effective_luck))
        pool_r.append({"idx": i, "w": w})
        total_w += w

    rnd = random.random() * total_w
    rar_idx = pool_r[-1]["idx"]
    for p in pool_r:
        if rnd < p["w"]:
            rar_idx = p["idx"]
            break
        rnd -= p["w"]

    rar_idx = max(min_idx, rar_idx)

    # Лимит Divine: не более 75 на сервере и максимум 1 Divine в руки одному игроку!
    if rar_idx == 9 and cur is not None:
        cur.execute("SELECT COUNT(*) FROM usernames WHERE rarity = 'Divine' AND is_saved = 1")
        div_cnt = cur.fetchone()[0] or 0
        user_has_divine = False
        if user_id:
            cur.execute("SELECT 1 FROM usernames WHERE owner_id = ? AND rarity = 'Divine' AND is_saved = 1 LIMIT 1", (user_id,))
            if cur.fetchone():
                user_has_divine = True
        if div_cnt >= DIVINE_SERVER_LIMIT or user_has_divine:
            rar_idx = 8

    return fast_build_item_in_memory(item_type, rar_idx, luck)

def ensure_unique_tag_clean(cur, cand: dict):
    """Никаких TON3, GOLD5 и прочего мусора! Генерируем только чистые номера и живые ники."""
    cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (cand["tag"],))
    if not cur.fetchone():
        return cand

    rar = cand["rarity"]
    if cand["type"] == "username":
        pool_words = WORDS.get(rar, REAL_CHAT_USERNAMES)[:]
        random.shuffle(pool_words)
        for w in pool_words:
            test_tag = f"@{w.strip()}"
            cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (test_tag,))
            if not cur.fetchone():
                cand["tag"] = test_tag
                return cand
        cand["tag"] = f"{cand['tag']}_{random.randint(10, 99)}"
    elif cand["type"] == "number":
        for _ in range(15):
            test_num = f"+888 {random.randint(100, 999)} {random.randint(100, 999)}"
            cur.execute("SELECT 1 FROM usernames WHERE tag = ?", (test_num,))
            if not cur.fetchone():
                cand["tag"] = test_num
                return cand
        cand["tag"] = f"+888 {random.randint(1000, 9999)} {random.randint(10, 99)}"
    else:
        base_g = cand["tag"].split("#")[0].strip()
        badge = " [BLACKOUT]" if "[BLACKOUT]" in cand["tag"] else (" [MATCH]" if "[MATCH]" in cand["tag"] else "")
        cand["tag"] = f"{base_g} #{random.randint(101, 9999)}{badge}"
    return cand

def calc_subs_and_multiplier(subs_count: int) -> float:
    """До 1,000,000 подписчиков = множитель до x10.0!"""
    s = min(1000000, max(0, int(subs_count or 0)))
    if s <= 0:
        return 1.0
    if s < 10000:
        return round(1.0 + (s / 10000.0) * 0.35, 2)
    if s < 50000:
        return round(1.35 + ((s - 10000) / 40000.0) * 0.85, 2)
    return round(2.20 + ((s - 50000) / 950000.0) * 7.80, 2)

def get_clan_bonus_multiplier(cur, clan_id: str) -> float:
    if not clan_id: return 1.0
    cur.execute("SELECT level, members_count FROM clans WHERE clan_id = ?", (clan_id,))
    row = cur.fetchone()
    if not row: return 1.0
    lvl, mems = row
    bonus_pct = 5.0 + (lvl * 1.5) + min(25.0, mems * 0.3)
    return 1.0 + (bonus_pct / 100.0)

def process_passive_income(cur, user_id: int):
    now = int(time.time())
    cur.execute("""
        SELECT balance, last_claim, smm_lvl, buyer_lvl, ai_boost, vip_until, clan_id, ref_by,
               tax_shield_until, tax_raid_amount, tax_raid_deadline, unlocked_titles
        FROM users WHERE tg_user_id = ?
    """, (user_id,))
    u = cur.fetchone()
    if not u: return 0.0
    (balance, last_claim, smm, buyer, ai_b, vip_until, clan_id, ref_by,
     tax_until, raid_amt, raid_dl, titles_raw) = u

    if last_claim <= 0:
        cur.execute("UPDATE users SET last_claim = ? WHERE tg_user_id = ?", (now, user_id))
        return 0.0

    elapsed = min(max(0, now - last_claim), 43200)
    if elapsed < 2: return 0.0

    # Случайный спавн налоговой облавы ОБЭП с фиксацией суммы и таймером 24 часа!
    if vip_until <= now and tax_until <= now and (raid_dl or 0) <= now:
        if random.random() < 0.20 and balance >= 25000:
            raid_amt = max(2500.0, round(balance * 0.10))
            raid_dl = now + 86400
            cur.execute("UPDATE users SET tax_raid_amount = ?, tax_raid_deadline = ? WHERE tg_user_id = ?", (raid_amt, raid_dl, user_id))

    # Начисляем подписчиков на активные каналы (~1.66 саба/сек -> ~6000 за час -> 1M за ~7 дней)
    cur.execute("""
        SELECT tag, income_per_sec, subs_count
        FROM usernames
        WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90 AND is_saved = 1 AND on_market = 0 AND is_staked = 0
    """, (user_id,))
    eq_rows = cur.fetchall()
    ch_inc_total = 0.0
    max_subs_seen = 0
    gain_subs = max(1, int(elapsed * 1.66))

    for tag, base_inc, old_subs in eq_rows:
        new_subs = min(1000000, int(old_subs or 0) + gain_subs)
        max_subs_seen = max(max_subs_seen, new_subs)
        sub_mult = calc_subs_and_multiplier(new_subs)
        ch_inc_total += float(base_inc or 0.0) * sub_mult
        cur.execute("UPDATE usernames SET subs_count = ? WHERE tag = ? AND owner_id = ?", (new_subs, tag, user_id))

    # Авто-выдача титулов за подписчиков (10K, 50K, 1M)
    titles_list = json.loads(titles_raw or '["Магнат"]')
    changed_t = False
    if max_subs_seen >= 10000 and "Начинающий" not in titles_list:
        titles_list.append("Начинающий"); changed_t = True
    if max_subs_seen >= 50000 and "Трендовый" not in titles_list:
        titles_list.append("Трендовый"); changed_t = True
    if max_subs_seen >= 1000000 and "Медиагигант" not in titles_list:
        titles_list.append("Медиагигант"); changed_t = True
    if changed_t:
        cur.execute("UPDATE users SET unlocked_titles = ? WHERE tg_user_id = ?", (json.dumps(titles_list, ensure_ascii=False), user_id))

    cur.execute("SELECT MAX(num_multi), SUM(income_per_sec) FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot = 99 AND is_saved = 1 AND on_market = 0 AND is_staked = 0", (user_id,))
    num_row = cur.fetchone()
    num_mult = min(100.0, float(num_row[0] or 1.0))
    num_direct = float(num_row[1] or 0.0)

    mgr_mult = (1.0 + smm * 0.06) * (1.0 + buyer * 0.12) * (1.5 if ai_b > 0 else 1.0)
    base_total = ((ch_inc_total * mgr_mult * num_mult) if ch_inc_total > 0 else 0.0) + (num_direct * mgr_mult * 0.25)

    if vip_until > now:
        base_total *= 1.5
    if clan_id:
        base_total *= get_clan_bonus_multiplier(cur, clan_id)
    if (raid_dl or 0) > now and (raid_amt or 0) > 0:
        base_total *= 0.75

    base_total = min(MAX_PASSIVE_PER_SEC, base_total)

    earned = round(base_total * elapsed, 2)
    cur.execute("UPDATE users SET balance = balance + ?, last_claim = ? WHERE tg_user_id = ?", (earned, now, user_id))

    if earned > 0 and ref_by:
        ref_cut = round(earned * 0.10, 2)
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (ref_cut, ref_by))
        cur.execute("UPDATE users SET contrib_gram = contrib_gram + ? WHERE tg_user_id = ?", (ref_cut, user_id))

    return earned

def settle_expired_auctions(cur):
    now = int(time.time())
    cur.execute("""
        SELECT lot_id, tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id,
               currency, current_price, highest_bidder_id
        FROM market_lots WHERE ends_at <= ?
    """, (now,))
    for lot in cur.fetchall():
        lid, tag, itype, rar, inc, num_m, reas, seller_id, curr, price, winner_id = lot
        curr = curr or "gram"
        if winner_id:
            if itype == "nat_phone":
                cur.execute("UPDATE users SET national_phone = ? WHERE tg_user_id = ?", (tag, winner_id))
            else:
                cur.execute("""
                    INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
                    VALUES (?, ?, ?, ?, 95, ?, ?, ?, ?, 0, 0, 1, 0, ?)
                """, (tag, itype, winner_id, rar, inc, round(price * 0.85, 0) if curr == 'gram' else 500000, num_m or 1.5, reas, now))
            if seller_id and seller_id > 0:
                if curr == "stars":
                    cur.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE tg_user_id = ?", (max(1, int(price * 0.95)), seller_id))
                else:
                    cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(price * 0.95, 2), seller_id))
        else:
            if seller_id and seller_id > 0 and itype != "nat_phone":
                cur.execute("UPDATE usernames SET on_market = 0, is_saved = 1 WHERE tag = ? AND owner_id = ?", (tag, seller_id))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (lid,))

def auto_sell_unsaved(cur, user_id: int) -> float:
    cur.execute("SELECT SUM(sell_price) FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0 AND is_staked = 0", (user_id,))
    val = cur.fetchone()[0]
    if val and val > 0:
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (val, user_id))
        cur.execute("DELETE FROM usernames WHERE owner_id = ? AND is_saved = 0 AND on_market = 0 AND is_staked = 0", (user_id,))
        return float(val)
    return 0.0

# ==========================================
# МОДЕЛИ ЗАПРОСОВ
# ==========================================
class ReqLogin(BaseModel): user_id: int; username: str = "Player"; ref_by: str = ""; init_data: str = ""
class ReqCountrySelect(BaseModel): user_id: int; country_code: str; mask_nft_tag: str = ""
class ReqNatPhoneTransfer(BaseModel): user_id: int; target_username: str = ""; mode: str = "gift"; auction_price: float = 100000000.0
class ReqMint(BaseModel): user_id: int; item_type: str = "username"; tier: str = "tier_0"; spin_count: int = 1; auto_save_min_idx: int = 0; init_data: str = ""
class ReqCaseOpen(BaseModel): user_id: int; case_key: str; count: int = 1; use_stars_bal: int = 0
class ReqAction(BaseModel): user_id: int; tag: str; action_type: str; slot: int = 0; init_data: str = ""
class ReqBulkSell(BaseModel): user_id: int; rarities: list[str]
class ReqRepair(BaseModel): user_id: int; tag: str; use_kit: int = 0
class ReqCraft(BaseModel): user_id: int; tags: list[str]; init_data: str = ""
class ReqDuel(BaseModel): user_id: int; tag: str; bet: float
class ReqUpgradeItem(BaseModel): user_id: int; tag: str; target_mult: int
class ReqCrashBet(BaseModel): user_id: int; bet: float; target_x: float = 2.0
class ReqRocketCashout(BaseModel): user_id: int; current_x: float
class ReqVaultHack(BaseModel): user_id: int; cell: int; use_lockpick: int = 0
class ReqMinesStart(BaseModel): user_id: int; mode: str = "gram"; bet: float = 1000.0; tag: str = ""; bombs: int = 5
class ReqMinesClick(BaseModel): user_id: int; cell: int
class ReqJackpotWheel(BaseModel): user_id: int; tag: str = ""; bet: float = 0.0
class ReqBankStake(BaseModel): user_id: int; stake_type: str = "item"; tag: str = ""; amount: float = 0.0; hours: int = 6
class ReqBankClaim(BaseModel): user_id: int; stake_id: int
class ReqCheckCreate(BaseModel): user_id: int; amount: float
class ReqTaxResolve(BaseModel): user_id: int; method: str
class ReqClanCreate(BaseModel): user_id: int; name: str
class ReqClanAction(BaseModel): user_id: int; clan_id: str = ""; amount: float = 0.0; target_uid: int = 0
class ReqMuseumSet(BaseModel): user_id: int; tags: list[str]
class ReqLotteryBuy(BaseModel): user_id: int; count: int = 1
class ReqShredder(BaseModel): user_id: int; tags: list[str] = []; shop_item: str = ""
class ReqCustomize(BaseModel): user_id: int; nick_color: str = "#f8fafc"; custom_title: str = "Магнат"; profile_frame: str = "default"
class ReqMarketCreate(BaseModel): user_id: int; username: str; tag: str; currency: str = "gram"; is_auction: int = 0; price: float = 15000.0; hours: int = 3
class ReqMarketInteract(BaseModel): user_id: int; username: str; lot_id: int; act: str; custom_bid: float = 0.0
class ReqAdminAction(BaseModel): admin_id: int; admin_username: str = ""; target_query: str = ""; action: str; amount: float = 0.0; extra: str = ""
class ReqSimple(BaseModel): user_id: int; key: str = ""

@app.get("/")
def serve_index():
    if os.path.exists("index.html"): return FileResponse("index.html")
    return HTMLResponse("<h2>index.html not found</h2>", status_code=404)

@app.get("/api/check_sub/{uid}")
async def check_channel_sub(uid: int):
    is_sub = False
    try:
        member = await bot.get_chat_member(chat_id=NEWS_CHANNEL, user_id=uid)
        if member.status in ["member", "administrator", "creator"]:
            is_sub = True
    except Exception:
        is_sub = True

    if is_sub:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT sub_verified FROM users WHERE tg_user_id = ?", (uid,))
        row = cur.fetchone()
        if row and row[0] == 0:
            cur.execute("UPDATE users SET sub_verified = 1, balance = balance + 15000.0 WHERE tg_user_id = ?", (uid,))
            conn.commit()
        conn.close()
    return {"subscribed": is_sub}

def apply_ref_bonus_and_check_3_friends(cur, ref_uid: int):
    now = int(time.time())
    cur.execute("SELECT refs_count, ref_3_rewarded, luck_until FROM users WHERE tg_user_id = ?", (ref_uid,))
    r_row = cur.fetchone()
    if not r_row: return
    old_cnt, r3_done, l_until = r_row
    nc = old_cnt + 1
    rew = 25000.0 if nc == 1 else (75000.0 if nc == 2 else (250000.0 if nc == 5 else (5000000.0 if nc == 20 else 35000.0)))
    cur.execute("UPDATE users SET refs_count = ?, balance = balance + ? WHERE tg_user_id = ?", (nc, rew, ref_uid))
    if nc >= 3 and (r3_done or 0) == 0:
        new_until = max(now, l_until or 0) + 10800
        cur.execute("UPDATE users SET luck_multi = GREATEST(luck_multi, 2.0), luck_until = ?, ref_3_rewarded = 1 WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET luck_multi = MAX(luck_multi, 2.0), luck_until = ?, ref_3_rewarded = 1 WHERE tg_user_id = ?", (new_until, ref_uid))

@app.post("/api/login")
def login(data: ReqLogin):
    check_rate(data.user_id, 15, 3.0)
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())

    parsed_ref = None
    raw_r = (data.ref_by or "").strip()
    if raw_r.startswith("ref_"):
        try: parsed_ref = int(raw_r.split("_")[1])
        except Exception: pass
    elif raw_r.isdigit():
        parsed_ref = int(raw_r)

    cur.execute("SELECT ref_by FROM users WHERE tg_user_id = ?", (data.user_id,))
    existing = cur.fetchone()

    if not existing:
        valid_ref = None
        if parsed_ref and parsed_ref != data.user_id:
            cur.execute("SELECT 1 FROM users WHERE tg_user_id = ?", (parsed_ref,))
            if cur.fetchone():
                valid_ref = parsed_ref
                apply_ref_bonus_and_check_3_friends(cur, valid_ref)
        start_bal = 35000.0 if valid_ref else 15000.0
        cur.execute("""
            INSERT INTO users (tg_user_id, username, balance, level, xp, ref_by, tax_shield_until, last_claim, created_at)
            VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?)
        """, (data.user_id, data.username, start_bal, valid_ref, now + 7200, now, now))
    else:
        cur.execute("UPDATE users SET username = ? WHERE tg_user_id = ?", (data.username, data.user_id))
        auto_sell_unsaved(cur, data.user_id)
        process_passive_income(cur, data.user_id)

    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/state/{uid}")
def get_state(uid: int, uname: str = ""):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)
    process_passive_income(cur, uid)
    conn.commit()

    cur.execute("""
        SELECT member_number, username, balance, stars_balance, level, xp, season_xp, season_claimed,
               smm_lvl, buyer_lvl, ai_boost, luck_multi, luck_until, vip_until, max_hold, max_channels,
               refs_count, ref_3_rewarded, clan_id, total_spins, pity_100, pity_500, last_wheel, last_vault,
               daily_streak, last_daily, q_spins, q_rare, q_crafts, q_duels, q_claimed,
               w_spins, w_cases, w_duels, w_claimed, ach_stats, ach_claimed, albums_claimed, contracts_done,
               tax_shield_until, tax_raid_amount, tax_raid_deadline, duel_wins, auto_save_min_idx,
               sub_verified, notify_merchant, gears, repair_kits, lockpicks, museum_tags, museum_likes,
               lottery_tickets, nick_color, custom_title, profile_frame, unlocked_titles,
               country_code, national_phone, masked_by_nft, last_story_at
        FROM users WHERE tg_user_id = ?
    """, (uid,))
    u = cur.fetchone()
    if not u:
        conn.close(); raise HTTPException(404, "User not found")

    (mem_num, db_uname, bal, stars_bal, lvl, xp, s_xp, s_cl, smm, buyer, ai_b, luck_m, luck_u, vip_u, max_h, max_ch,
     refs, ref3_rew, clan_id, tot_spins, p100, p500, l_wheel, l_vault, d_streak, l_daily,
     qs, qr, qc, qd, q_cl, ws, wc, wd, w_cl, a_st, a_cl, alb_cl, cnt_done,
     tax_u, raid_amt, raid_dl, d_wins, auto_idx, sub_v, notif_m,
     gears, rep_kits, lockpicks, mus_tags, mus_likes, lot_tix, n_col, c_title, p_frame, unl_titles,
     country_code, nat_phone, masked_nft, last_story) = u

    cur.execute("SELECT COUNT(*) FROM usernames WHERE rarity = 'Divine' AND is_saved = 1")
    divine_minted_cnt = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT tag, item_type, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons,
               is_equipped, channel_slot, is_staked, is_verified, last_duel_at, subs_count
        FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0
        ORDER BY sell_price DESC
    """, (uid,))
    tags = []
    for r in cur.fetchall():
        q_clamped = min(100, max(10, int(r[3] if r[3] is not None else 95)))
        subs_c = int(r[13] or 0)
        tags.append({
            "tag": r[0], "type": r[1] or "username", "rarity": r[2], "q": q_clamped,
            "inc": round(float(r[4] or 1.0), 2), "sell": round(float(r[5] or 50.0)),
            "num_x": round(float(r[6] or 1.5), 2), "reasons": r[7].split("|") if r[7] else [],
            "eq": r[8], "slot": r[9], "staked": r[10] or 0, "verified": r[11] or 0,
            "duel_cd": max(0, (int(r[12] or 0) + 120) - now),
            "subs": subs_c, "subs_mult": calc_subs_and_multiplier(subs_c)
        })

    cur.execute("""
        SELECT stake_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at
        FROM staked_deposits WHERE user_id = ? AND claimed = 0 ORDER BY stake_id DESC
    """, (uid,))
    stakes = [{
        "id": r[0], "type": r[1], "tag": r[2], "principal": r[3],
        "reward": r[4], "hours": r[5], "left": max(0, r[6] - now)
    } for r in cur.fetchall()]

    cur.execute("SELECT username, level, contrib_gram, contrib_stars FROM users WHERE ref_by = ? ORDER BY contrib_gram DESC LIMIT 50", (uid,))
    referrals_list = [{
        "username": r[0] or "Игрок", "level": r[1],
        "gram": round(r[2] or 0.0, 0), "stars": r[3] or 0
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT tg_user_id, username, balance, level, duel_wins, museum_tags, museum_likes,
               nick_color, custom_title, country_code, national_phone, masked_by_nft
        FROM users ORDER BY balance DESC LIMIT 50
    """)
    leaders = [{
        "uid": r[0], "username": r[1] or "Магнат", "balance": round(r[2], 0), "level": r[3],
        "wins": r[4] or 0, "museum": json.loads(r[5] or "[]"), "likes": r[6] or 0,
        "color": r[7] or "#f8fafc", "title": r[8] or "Магнат",
        "country": r[9] or "RU", "nat_phone": r[11] if r[11] else (r[10] or ""),
        "is_masked": bool(r[11])
    } for r in cur.fetchall()]

    cur.execute("SELECT clan_id, name, owner_id, level, treasury, members_count, max_members FROM clans ORDER BY level DESC, treasury DESC")
    clans = [{
        "id": r[0], "name": r[1], "owner_id": r[2], "level": r[3],
        "treasury": round(r[4], 0), "members": r[5], "max_members": r[6],
        "bonus": round(5.0 + (r[3] * 1.5) + min(25.0, r[5] * 0.3), 1)
    } for r in cur.fetchall()]

    cur.execute("""
        SELECT lot_id, tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, seller_name,
               currency, is_auction, current_price, buyout_price, highest_bidder_id, highest_bidder_name, bids_count, ends_at
        FROM market_lots WHERE ends_at > ? ORDER BY created_at DESC LIMIT 60
    """, (now,))
    market = [{
        "lot_id": r[0], "tag": r[1], "type": r[2], "rarity": r[3], "inc": round(float(r[4] or 1.0), 2),
        "num_x": round(float(r[5] or 1.5), 2), "reasons": r[6].split("|") if r[6] else [],
        "seller_id": r[7], "seller_name": r[8], "currency": r[9] or "gram",
        "is_auction": r[10], "price": r[11], "buyout": r[12], "bidder_id": r[13],
        "bidder_name": r[14], "bids": r[15], "left": max(0, r[16] - now)
    } for r in cur.fetchall()]

    conn.close()
    is_vip = vip_u > now
    museum_luck_bonus = min(1.5, (mus_likes or 0) * 0.01)
    temp_boost_active = (luck_u or 0) > now
    active_luck = ((luck_m if temp_boost_active else 1.0) + museum_luck_bonus) * (1.35 if is_vip else 1.0)
    actual_refs = max(refs, len(referrals_list))

    pass_lvl, pass_cur_xp, pass_req_xp = get_pass_level_info(s_xp or 0)
    raid_active = ((raid_dl or 0) > now) and ((raid_amt or 0) > 0) and not is_vip

    return {
        "is_admin": is_user_admin(uid, uname or db_uname),
        "member_number": mem_num, "balance": round(bal, 2), "stars_balance": int(stars_bal or 0),
        "level": lvl, "xp": xp,
        "season_xp": s_xp, "pass_lvl": pass_lvl, "pass_cur_xp": pass_cur_xp, "pass_req_xp": pass_req_xp,
        "pass_skip_stars": get_pass_skip_cost_stars(pass_lvl),
        "season_claimed": json.loads(s_cl or "[]"),
        "smm": smm, "smm_max": MAX_SMM_LVL, "smm_cost": get_smm_upgrade_cost(smm),
        "buyer": buyer, "buyer_max": MAX_BUYER_LVL, "buyer_cost": get_buyer_upgrade_cost(buyer),
        "ai_boost": ai_b,
        "luck_multi": round(active_luck, 2),
        "luck_left": max(0, (luck_u or 0) - now),
        "is_vip": is_vip, "max_hold": max_h, "max_channels": max_ch,
        "refs_count": actual_refs, "ref_3_done": (ref3_rew or 0) == 1 or actual_refs >= 3,
        "referrals_list": referrals_list,
        "clan_id": clan_id, "total_spins": tot_spins, "pity_100": p100, "pity_500": p500,
        "divine_minted": divine_minted_cnt, "divine_limit": DIVINE_SERVER_LIMIT,
        "wheel_wait": max(0, (l_wheel + 1800) - now),
        "vault_wait": max(0, ((l_vault or 0) + 3600) - now),
        "story_wait": max(0, ((last_story or 0) + 86400) - now),
        "daily_streak": d_streak, "can_daily": (now - l_daily) >= 86400,
        "quests": {"spins": qs, "rare": qr, "crafts": qc, "duels": qd or 0, "claimed": json.loads(q_cl or "[]")},
        "weekly": {"spins": ws or 0, "cases": wc or 0, "duels": wd or 0, "claimed": json.loads(w_cl or "[]")},
        "ach": {"stats": json.loads(a_st or "{}"), "claimed": json.loads(a_cl or "[]")},
        "albums_claimed": json.loads(alb_cl or "[]"),
        "contracts": get_daily_vip_contracts(),
        "contracts_done": json.loads(cnt_done or "[]"),
        "stakes": stakes,
        "tax_active": raid_active,
        "tax_raid_amount": round(raid_amt or 0.0),
        "tax_raid_left": max(0, (raid_dl or 0) - now),
        "tax_shield_left": max(0, (tax_u or 0) - now),
        "duel_wins": d_wins or 0,
        "gears": gears or 0, "repair_kits": rep_kits or 0, "lockpicks": lockpicks or 0,
        "museum_tags": json.loads(mus_tags or "[]"), "museum_likes": mus_likes or 0,
        "lottery": {"my_tickets": lot_tix or 0, "pot": LOTTERY_STATE["pot"], "last_winner": LOTTERY_STATE["last_winner"], "last_win": LOTTERY_STATE["last_win_amount"]},
        "profile": {
            "color": n_col or "#f8fafc", "title": c_title or "Магнат", "frame": p_frame or "default",
            "unlocked_titles": json.loads(unl_titles or '["Магнат"]'),
            "country": country_code or "", "nat_phone": nat_phone or "", "masked_by_nft": masked_nft or ""
        },
        "hot_series": get_daily_hot_series(),
        "merchant": get_active_merchant_offer(),
        "notify_merchant": (notif_m or 0) == 1,
        "auto_save_min_idx": auto_idx, "sub_verified": sub_v,
        "leaders": leaders, "clans": clans, "tags": tags, "market": market
    }

# ==========================================
# СТРАНЫ, НАЦ. НОМЕРА И ПЕРЕДАЧА / АУКЦИОН НАЦ. НОМЕРА
# ==========================================
@app.post("/api/country/select")
def select_or_change_country(data: ReqCountrySelect):
    if data.country_code not in COUNTRIES:
        raise HTTPException(400, "Выберите корректную страну")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT country_code, national_phone FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    old_cc, old_phone = row[0] or "", row[1] or ""

    if data.mask_nft_tag:
        if data.mask_nft_tag == "CLEAR":
            cur.execute("UPDATE users SET masked_by_nft = '' WHERE tg_user_id = ?", (data.user_id,))
            conn.commit(); conn.close()
            return {"status": "ok", "masked_by_nft": ""}
        cur.execute("SELECT rarity FROM usernames WHERE tag = ? AND owner_id = ? AND item_type = 'number' AND is_saved = 1", (data.mask_nft_tag, data.user_id))
        n_row = cur.fetchone()
        if not n_row:
            conn.close(); raise HTTPException(400, "Номер +888 не найден в Сейфе!")
        r_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == n_row[0]), 0)
        if r_idx < 5:
            conn.close(); raise HTTPException(400, "Скрыть национальный номер в профиле можно только номером +888 от редкости Mythic и выше!")
        cur.execute("UPDATE users SET masked_by_nft = ? WHERE tg_user_id = ?", (data.mask_nft_tag, data.user_id))
        conn.commit(); conn.close()
        return {"status": "ok", "masked_by_nft": data.mask_nft_tag}

    new_phone = old_phone
    if old_cc != data.country_code or not old_phone:
        new_phone = generate_national_phone(data.country_code)
        cur.execute("UPDATE users SET country_code = ?, national_phone = ?, masked_by_nft = '' WHERE tg_user_id = ?",
                    (data.country_code, new_phone, data.user_id))
        conn.commit()
    conn.close()
    return {"status": "ok", "country": data.country_code, "nat_phone": new_phone}

@app.post("/api/country/transfer_phone")
def transfer_or_sell_national_phone(data: ReqNatPhoneTransfer):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, country_code, national_phone, username FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, my_cc, my_phone, my_uname = cur.fetchone()
    if not my_phone:
        conn.close(); raise HTTPException(400, "У вас нет национального номера!")

    if data.mode == "auction":
        fee = 100000000.0
        if bal < fee:
            conn.close(); raise HTTPException(400, "Пошлина за выставление национального номера на аукцион — 100,000,000 GRAM!")
        start_p = max(100000000.0, float(data.auction_price or 100000000.0))
        now = int(time.time())
        new_random_phone = generate_national_phone(my_cc or "RU")
        cur.execute("UPDATE users SET balance = balance - ?, national_phone = ? WHERE tg_user_id = ?", (fee, new_random_phone, data.user_id))
        cur.execute("""
            INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, seller_name, currency, is_auction, start_price, current_price, buyout_price, ends_at, created_at)
            VALUES (?, 'nat_phone', 'Luxury', 0, 1.0, ?, ?, ?, 'gram', 1, ?, ?, ?, ?, ?)
        """, (my_phone, f"Национальный номер ({my_cc})", data.user_id, my_uname or "Магнат", start_p, start_p, start_p * 2.5, now + 21600, now))
        conn.commit(); conn.close()
        return {"status": "ok", "message": f"Номер {my_phone} выставлен на аукцион! Вам выдан новый номер {new_random_phone}."}

    # Прямая передача земляку из той же страны за 500,000,000 GRAM
    fee = 500000000.0
    if bal < fee:
        conn.close(); raise HTTPException(400, "Стоимость прямой передачи номера игроку своей страны — 500,000,000 GRAM!")
    target_clean = (data.target_username or "").strip().replace("@", "")
    cur.execute("SELECT tg_user_id, country_code FROM users WHERE LOWER(username) = LOWER(?)", (target_clean,))
    t_row = cur.fetchone()
    if not t_row:
        conn.close(); raise HTTPException(400, f"Игрок @{target_clean} не найден!")
    t_uid, t_cc = t_row
    if t_cc != my_cc:
        conn.close(); raise HTTPException(400, "Передать номер напрямую можно только игроку из вашей страны!")

    new_random_phone = generate_national_phone(my_cc or "RU")
    cur.execute("UPDATE users SET balance = balance - ?, national_phone = ? WHERE tg_user_id = ?", (fee, new_random_phone, data.user_id))
    cur.execute("UPDATE users SET national_phone = ? WHERE tg_user_id = ?", (my_phone, t_uid))
    conn.commit(); conn.close()
    return {"status": "ok", "message": f"Номер {my_phone} передан игроку @{target_clean}!"}

# ==========================================
# СТОРИСЫ TELEGRAM (500,000 G × УРОВЕНЬ ИГРОКА)
# ==========================================
@app.post("/api/story/claim")
def claim_story_reward(data: ReqSimple):
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT level, last_story_at FROM users WHERE tg_user_id = ?", (data.user_id,))
    lvl, last_st = cur.fetchone()
    if (now - (last_st or 0)) < 86400:
        left_h = int((86400 - (now - (last_st or 0))) // 3600) + 1
        conn.close(); raise HTTPException(400, f"Награда за Сторис доступна раз в 24ч! Подождите ещё {left_h} ч.")
    reward = float(max(1, lvl) * 500000)
    cur.execute("UPDATE users SET balance = balance + ?, last_story_at = ?, season_xp = season_xp + 45 WHERE tg_user_id = ?", (reward, now, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "reward": reward}

# ==========================================
# ПРОКРУТ С ГАРАНТАМИ x5 (100) И x25 (500)
# ==========================================
def execute_spins_internal(cur, user_id: int, item_type: str, tier: str, count: int, cost: float, auto_save_min_idx: int = 0):
    now = int(time.time())
    cur.execute("""
        SELECT balance, level, xp, season_xp, luck_multi, luck_until, vip_until,
               total_spins, pity_100, pity_500, q_spins, q_rare, w_spins, ach_stats, max_hold, museum_likes
        FROM users WHERE tg_user_id = ?
    """, (user_id,))
    u = cur.fetchone()
    if not u: raise HTTPException(404, "User not found")
    (bal, lvl, xp, s_xp, luck_m, luck_u, vip_u, tot_s, p100, p500, qs, qr, ws, ach_raw, max_h, mus_l) = u

    if bal < cost:
        raise HTTPException(400, f"Не хватает на ставку: нужно {int(cost):,} GRAM")

    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (user_id,))
    cur_hold_cnt = cur.fetchone()[0]

    is_vip = vip_u > now
    base_luck = ((luck_m if luck_u > now else 1.0) + min(1.5, (mus_l or 0) * 0.01)) * (1.35 if is_vip else 1.0)
    ach_stats = json.loads(ach_raw or "{}")

    drops = []
    added_xp = 0
    ws = (ws or 0) + count
    for _ in range(count):
        tot_s += 1; p100 += 1; p500 += 1; qs += 1; s_xp += 3

        choice_pool = 1
        spin_luck = base_luck
        pity_factor = None

        if p500 >= 500:
            choice_pool = 25
            spin_luck = max(base_luck * 25.0, 25.0)
            p500 = 0; p100 = 0
            pity_factor = {"label": "ГАРАНТ 500-ГО ПРОКРУТА (Удача ×25)", "mult": "×25"}
        elif p100 >= 100:
            choice_pool = 5
            spin_luck = max(base_luck * 5.0, 5.0)
            p100 = 0
            pity_factor = {"label": "ГАРАНТ 100-ГО ПРОКРУТА (Удача ×5)", "mult": "×5"}

        best_cand = None
        for _ in range(choice_pool):
            c_try = roll_single_candidate_fast(cur, item_type, tier, spin_luck, user_id)
            if best_cand is None or c_try["sell"] > best_cand["sell"]:
                best_cand = c_try

        cand = ensure_unique_tag_clean(cur, best_cand)
        if cand["rar_idx"] >= 2:
            qr += 1
        ach_stats[cand["rarity"]] = ach_stats.get(cand["rarity"], 0) + 1

        save_flag = 0
        if cand["rar_idx"] >= auto_save_min_idx and cur_hold_cnt < max_h:
            save_flag = 1
            cur_hold_cnt += 1

        cur.execute("""
            INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?)
        """, (cand["tag"], cand["type"], user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], save_flag, now))

        factors_out = list(cand.get("factors", []))
        if pity_factor:
            factors_out.insert(0, pity_factor)

        drops.append({
            "tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
            "q": cand["quality"], "inc": cand["inc"], "xp": cand["xp"], "sell": cand["sell"],
            "num_x": cand["num_multi"], "auto_saved": save_flag == 1,
            "reasons": cand["reasons"].split("|"), "factors": factors_out
        })
        added_xp += cand["xp"]

    new_bal = round(bal - cost, 2)
    new_xp = xp + added_xp
    new_lvl = lvl
    while new_xp >= new_lvl * 150:
        new_xp -= new_lvl * 150
        new_lvl += 1

    cur.execute("""
        UPDATE users SET balance = ?, level = ?, xp = ?, season_xp = ?, total_spins = ?,
                         pity_100 = ?, pity_500 = ?, q_spins = ?, q_rare = ?, w_spins = ?, ach_stats = ?, auto_save_min_idx = ?
        WHERE tg_user_id = ?
    """, (new_bal, new_lvl, new_xp, s_xp, tot_s, p100, p500, qs, qr, ws, json.dumps(ach_stats), auto_save_min_idx, user_id))

    return drops, new_bal, p100, p500

@app.post("/api/mint")
def mint(data: ReqMint):
    check_rate(data.user_id, 12, 2.0)
    if data.tier not in SPIN_TIERS: raise HTTPException(400, "Неверный тир прокрутки")
    if data.spin_count not in [1, 5]: raise HTTPException(400, "За GRAM доступно 1x или 5x")
    if data.user_id in TX_LOCKS: raise HTTPException(429, "Операция уже выполняется")

    TX_LOCKS.add(data.user_id)
    conn = get_db(); cur = conn.cursor()
    try:
        auto_sold = auto_sell_unsaved(cur, data.user_id)
        tier_info = SPIN_TIERS[data.tier]
        unit_cost = tier_info["n_cost"] if data.item_type == "number" else tier_info["u_cost"]
        total_cost = unit_cost * data.spin_count
        drops, new_bal, p100, p500 = execute_spins_internal(cur, data.user_id, data.item_type, data.tier, data.spin_count, total_cost, data.auto_save_min_idx)
        conn.commit()
        return {"drops": drops, "auto_sold": auto_sold, "balance": new_bal, "pity_100": p100, "pity_500": p500}
    finally:
        TX_LOCKS.discard(data.user_id)
        conn.close()

# ==========================================
# БОКСЫ (ОТКРЫТИЕ x1, x5, x10 ЗА GRAM ИЛИ С БАЛАНСА STARS!)
# ==========================================
def roll_case_drop_fast(cur, case_key: str, luck: float = 1.0, user_id: int = 0):
    c_info = CASES_CATALOG[case_key]
    itype = random.choice(c_info["types"])
    w_map = c_info["weights"]
    pool_c = []
    tot = 0
    min_r = min(w_map.keys())
    for r_idx, w_val in w_map.items():
        eff_w = int(w_val * (luck if r_idx > min_r else 1.0))
        pool_c.append((r_idx, eff_w))
        tot += eff_w

    rnd = random.random() * tot
    picked_idx = pool_c[-1][0]
    for r_idx, ew in pool_c:
        if rnd < ew:
            picked_idx = r_idx
            break
        rnd -= ew

    if picked_idx == 9 and cur is not None:
        cur.execute("SELECT COUNT(*) FROM usernames WHERE rarity = 'Divine' AND is_saved = 1")
        div_cnt = cur.fetchone()[0] or 0
        has_div = False
        if user_id:
            cur.execute("SELECT 1 FROM usernames WHERE owner_id = ? AND rarity = 'Divine' AND is_saved = 1 LIMIT 1", (user_id,))
            if cur.fetchone(): has_div = True
        if div_cnt >= DIVINE_SERVER_LIMIT or has_div:
            picked_idx = 8

    cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory(itype, picked_idx, luck))
    # Повышенная окупаемость донатных боксов за Stars!
    if c_info["curr"] == "stars":
        boost = 1.45 if case_key == "case_stars_lite" else (1.55 if case_key == "case_stars_founder" else 1.75)
        cand["sell"] = round(cand["sell"] * boost)
        cand["inc"] = round(cand["inc"] * 1.35, 2)

    tape = []
    for _ in range(28):
        f_idx = random.choice(list(w_map.keys()))
        f_type = random.choice(c_info["types"])
        f_item = fast_build_item_in_memory(f_type, f_idx, 1.0)
        tape.append({"tag": f_item["tag"], "rarity": f_item["rarity"], "type": f_type, "sell": f_item["sell"]})
    return cand, tape

@app.post("/api/cases/open")
def open_case_multi(data: ReqCaseOpen):
    check_rate(data.user_id, 10, 2.0)
    if data.case_key not in CASES_CATALOG:
        raise HTTPException(400, "Бокс не найден")
    cnt = data.count if data.count in [1, 5, 10] else 1
    c_info = CASES_CATALOG[data.case_key]

    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT balance, stars_balance, luck_multi, luck_until, vip_until, max_hold, w_cases FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, stars_bal, luck_m, luck_u, vip_u, max_h, w_cases = cur.fetchone()
    stars_bal = int(stars_bal or 0)

    total_price = c_info["price"] * cnt
    if c_info["curr"] == "stars":
        if stars_bal < total_price:
            conn.close(); raise HTTPException(400, f"На внутреннем счете нужно {total_price} ⭐️ Stars! Пополните баланс Stars в Магазине.")
    else:
        if bal < total_price:
            conn.close(); raise HTTPException(400, f"Недостаточно средств: нужно {total_price:,} GRAM")

    cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
    cur_hold = cur.fetchone()[0]
    if cur_hold + cnt > max_h:
        conn.close(); raise HTTPException(400, f"В Сейфе не хватит мест для {cnt} предметов ({cur_hold}/{max_h})!")

    eff_luck = (luck_m if luck_u > now else 1.0) * (1.35 if vip_u > now else 1.0)
    winners = []
    last_tape = []
    for _ in range(cnt):
        cand, tape = roll_case_drop_fast(cur, data.case_key, eff_luck, data.user_id)
        last_tape = tape
        cur.execute("""
            INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
        """, (cand["tag"], cand["type"], data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
        winners.append({
            "tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"],
            "q": cand["quality"], "inc": cand["inc"], "sell": cand["sell"], "num_x": cand["num_multi"],
            "reasons": cand["reasons"].split("|"), "eq": 0, "slot": 0, "staked": 0, "verified": 0, "duel_cd": 0
        })

    if c_info["curr"] == "stars":
        new_stars = stars_bal - int(total_price)
        new_bal = round(bal, 2)
        cur.execute("UPDATE users SET stars_balance = ?, season_xp = season_xp + ?, w_cases = ? WHERE tg_user_id = ?",
                    (new_stars, 25 * cnt, (w_cases or 0) + cnt, data.user_id))
    else:
        new_bal = round(bal - total_price, 2)
        new_stars = stars_bal
        cur.execute("UPDATE users SET balance = ?, season_xp = season_xp + ?, w_cases = ? WHERE tg_user_id = ?",
                    (new_bal, 20 * cnt, (w_cases or 0) + cnt, data.user_id))

    conn.commit(); conn.close()
    return {"winner": winners[0], "winners": winners, "tape": last_tape, "balance": new_bal, "stars_balance": new_stars}

# ==========================================
# ОПТОВАЯ ПРОДАЖА И РЕСТАВРАЦИЯ (КАП 100%)
# ==========================================
@app.post("/api/bulk_sell")
def bulk_sell_safe(data: ReqBulkSell):
    if not data.rarities:
        raise HTTPException(400, "Выберите хотя бы одну редкость для продажи!")
    conn = get_db(); cur = conn.cursor()
    ph = ",".join("?" for _ in data.rarities)
    cur.execute(f"""
        SELECT tag, sell_price FROM usernames
        WHERE owner_id = ? AND is_saved = 1 AND is_equipped = 0 AND on_market = 0 AND is_staked = 0
          AND rarity IN ({ph})
    """, [data.user_id, *data.rarities])
    rows = cur.fetchall()
    if not rows:
        conn.close(); raise HTTPException(400, "Нет свободных предметов выбранных редкостей в Сейфе!")

    total_earned = round(sum(r[1] for r in rows), 2)
    tags_to_del = [r[0] for r in rows]
    ph_del = ",".join("?" for _ in tags_to_del)
    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({ph_del})", [data.user_id, *tags_to_del])
    cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + ? WHERE tg_user_id = ?",
                (total_earned, min(100, len(rows) * 2), data.user_id))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit(); conn.close()
    return {"status": "ok", "count": len(rows), "earned": total_earned, "sold_tags": tags_to_del, "balance": round(new_bal, 2)}

@app.post("/api/repair_item")
def repair_worn_item(data: ReqRepair):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT quality_pct, sell_price, income_per_sec FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(400, "Предмет не найден в Сейфе!")
    qual, sell_p, inc = row
    qual = min(100, max(10, int(qual or 50)))
    if qual >= 100:
        conn.close(); raise HTTPException(400, "Предмет уже в идеальном состоянии (100%)!")

    cur.execute("SELECT balance, repair_kits FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, kits = cur.fetchone()

    cost = round(sell_p * 0.15)
    if data.use_kit == 1 and (kits or 0) > 0:
        cur.execute("UPDATE users SET repair_kits = repair_kits - 1 WHERE tg_user_id = ?", (data.user_id,))
        cost = 0
    else:
        if bal < cost:
            conn.close(); raise HTTPException(400, f"Для реставрации до 100% нужно {cost:,} GRAM (или Ремкомплект)!")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (cost, data.user_id))

    ratio = 100.0 / max(15.0, float(qual))
    new_sell = round(sell_p * min(2.0, ratio))
    new_inc = round(inc * min(2.0, ratio), 2)
    cur.execute("UPDATE usernames SET quality_pct = 100, sell_price = ?, income_per_sec = ? WHERE tag = ? AND owner_id = ?",
                (new_sell, new_inc, data.tag, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "new_q": 100, "new_sell": new_sell, "new_inc": new_inc, "cost": cost}

# ==========================================
# НАЛОГОВЫЙ РЕЙД ОБЭП С ФИКСИРОВАННОЙ СУММОЙ НА 24 ЧАСА
# ==========================================
@app.post("/api/tax_raid/resolve")
def resolve_tax_raid(data: ReqTaxResolve):
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id, vip_until, tax_raid_amount FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, clan_id, vip_u, fixed_amt = cur.fetchone()
    bribe = max(2500.0, round(float(fixed_amt or (bal * 0.10)), 2))

    if data.method == "bribe":
        if bal < bribe:
            conn.close(); raise HTTPException(400, f"Для оплаты предписания нужно {int(bribe):,} GRAM!")
        new_bal = round(bal - bribe, 2)
        cur.execute("UPDATE users SET balance = ?, tax_shield_until = ?, tax_raid_amount = 0, tax_raid_deadline = 0 WHERE tg_user_id = ?",
                    (new_bal, now + 28800, data.user_id))
        conn.commit(); conn.close()
        return {"win": True, "paid": bribe, "balance": new_bal, "message": f"Оплачено {int(bribe):,} GRAM. Каналам возвращено 100% мощности + иммунитет на 8 часов!"}

    clan_lvl = 0
    if clan_id:
        cur.execute("SELECT level FROM clans WHERE clan_id = ?", (clan_id,))
        c_row = cur.fetchone()
        if c_row: clan_lvl = c_row[0]

    pass_chance = min(0.80, 0.55 + clan_lvl * 0.015 + (0.15 if vip_u > now else 0.0))
    if random.random() <= pass_chance:
        cur.execute("UPDATE users SET tax_shield_until = ?, tax_raid_amount = 0, tax_raid_deadline = 0, season_xp = season_xp + 50 WHERE tg_user_id = ?",
                    (now + 28800, data.user_id))
        conn.commit(); conn.close()
        return {"win": True, "paid": 0, "balance": round(bal, 2), "message": "Юристы отбили проверку ОБЭП бесплатно! Иммунитет на 8 часов!"}
    else:
        fine = round(bribe * 2.0, 2)
        new_bal = max(0.0, round(bal - fine, 2))
        cur.execute("UPDATE users SET balance = ?, tax_shield_until = ?, tax_raid_amount = 0, tax_raid_deadline = 0 WHERE tg_user_id = ?",
                    (new_bal, now + 28800, data.user_id))
        conn.commit(); conn.close()
        return {"win": False, "paid": fine, "balance": new_bal, "message": f"ОБЭП выписал двойной штраф: -{int(fine):,} GRAM!"}

# ==========================================
# РАКЕТКА, САПЁР, ДУЭЛИ, КРАФТ
# ==========================================
def roll_rocket_crash_point() -> float:
    r = random.random()
    if r < 0.07: return 1.00
    raw_x = 0.93 / ((1.0 - r) ** 1.18)
    return round(min(1200.0, max(1.01, raw_x)), 2)

@app.post("/api/minigame/rocket/start")
def rocket_start_flight(data: ReqCrashBet):
    check_rate(data.user_id, 8, 2.0)
    if data.bet < 200: raise HTTPException(400, "Минимальная ставка — 200 GRAM")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < data.bet: conn.close(); raise HTTPException(400, "Недостаточно GRAM для старта!")
    new_bal = round(bal - data.bet, 2)
    cur.execute("UPDATE users SET balance = ?, season_xp = season_xp + 5 WHERE tg_user_id = ?", (new_bal, data.user_id))
    conn.commit(); conn.close()
    crash_x = roll_rocket_crash_point()
    ACTIVE_ROCKETS[data.user_id] = {"bet": float(data.bet), "crash_x": float(crash_x), "target_x": max(1.05, min(1200.0, float(data.target_x or 100.0))), "cashed": False}
    return {"status": "flying", "crash_x": crash_x, "balance": new_bal}

@app.post("/api/minigame/rocket/cashout")
def rocket_manual_cashout(data: ReqRocketCashout):
    sess = ACTIVE_ROCKETS.get(data.user_id)
    if not sess or sess.get("cashed"): raise HTTPException(400, "Полет уже завершен")
    claim_x = round(max(1.01, min(float(data.current_x or 1.01), sess["crash_x"])), 2)
    if claim_x > sess["crash_x"] or sess["crash_x"] <= 1.00:
        ACTIVE_ROCKETS.pop(data.user_id, None)
        raise HTTPException(400, f"Поздно! Ракета взорвалась на ×{sess['crash_x']}")
    sess["cashed"] = True
    ACTIVE_ROCKETS.pop(data.user_id, None)
    winnings = round(sess["bet"] * claim_x)
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 15 WHERE tg_user_id = ?", (winnings, data.user_id))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit(); conn.close()
    return {"win": True, "cashed_x": claim_x, "crash_x": sess["crash_x"], "winnings": winnings, "balance": round(new_bal, 2), "message": f"Выведено на ×{claim_x}! Получено +{winnings:,} GRAM!"}

def calc_mines_multiplier(bombs: int, opened_count: int) -> float:
    if opened_count <= 0: return 1.00
    prob = 1.0
    for i in range(opened_count): prob *= (25 - bombs - i) / (25 - i)
    return round(0.95 / max(0.0001, prob), 2)

@app.post("/api/minigame/mines/start")
def mines_start_game(data: ReqMinesStart):
    check_rate(data.user_id, 8, 2.0)
    bombs = max(3, min(20, int(data.bombs)))
    conn = get_db(); cur = conn.cursor()
    stake_val = float(data.bet)
    if data.mode == "item":
        cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
        row = cur.fetchone()
        if not row or row[1] == 1 or row[2] == 1 or row[3] == 1:
            conn.close(); raise HTTPException(400, "Выберите свободный предмет из Сейфа!")
        stake_val = float(row[0])
        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    else:
        if stake_val < 500: conn.close(); raise HTTPException(400, "Минимальная ставка — 500 GRAM")
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        bal = cur.fetchone()[0]
        if bal < stake_val: conn.close(); raise HTTPException(400, "Недостаточно GRAM!")
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (stake_val, data.user_id))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit(); conn.close()
    ACTIVE_MINES[data.user_id] = {"stake": stake_val, "bombs": bombs, "bomb_cells": set(random.sample(range(25), bombs)), "opened": set(), "active": True}
    return {"status": "started", "stake": stake_val, "bombs": bombs, "balance": round(new_bal, 2), "next_mult": calc_mines_multiplier(bombs, 1)}

@app.post("/api/minigame/mines/click")
def mines_click_cell(data: ReqMinesClick):
    sess = ACTIVE_MINES.get(data.user_id)
    if not sess or not sess["active"]: raise HTTPException(400, "Сначала нажмите «Начать игру»!")
    c = int(data.cell)
    if c < 0 or c >= 25 or c in sess["opened"]: raise HTTPException(400, "Ячейка уже открыта")
    if c in sess["bomb_cells"]:
        sess["active"] = False
        bombs_list = list(sess["bomb_cells"])
        ACTIVE_MINES.pop(data.user_id, None)
        return {"boom": True, "cell": c, "bomb_cells": bombs_list, "message": "БУМ! Вы нарвались на мину! Ставка сгорела."}
    sess["opened"].add(c)
    opened_cnt = len(sess["opened"])
    cur_mult = calc_mines_multiplier(sess["bombs"], opened_cnt)
    next_mult = calc_mines_multiplier(sess["bombs"], opened_cnt + 1) if (opened_cnt + sess["bombs"] < 25) else cur_mult
    return {"boom": False, "cell": c, "opened_count": opened_cnt, "cur_mult": cur_mult, "next_mult": next_mult, "current_win": round(sess["stake"] * cur_mult)}

@app.post("/api/minigame/mines/cashout")
def mines_cashout(data: ReqSimple):
    sess = ACTIVE_MINES.get(data.user_id)
    if not sess or not sess["active"] or len(sess["opened"]) == 0:
        raise HTTPException(400, "Откройте хотя бы 1 кристалл перед выводом!")
    sess["active"] = False
    mult = calc_mines_multiplier(sess["bombs"], len(sess["opened"]))
    payout = round(sess["stake"] * mult)
    bombs_list = list(sess["bomb_cells"])
    ACTIVE_MINES.pop(data.user_id, None)
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 20 WHERE tg_user_id = ?", (payout, data.user_id))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    new_bal = cur.fetchone()[0]
    conn.commit(); conn.close()
    return {"status": "cashed", "mult": mult, "payout": payout, "bomb_cells": bombs_list, "balance": round(new_bal, 2), "message": f"Забрано на ×{mult}! Выигрыш +{payout:,} GRAM!"}

@app.post("/api/duel")
def play_pvp_duel(data: ReqDuel):
    check_rate(data.user_id, 6, 2.0)
    if data.bet < 500: raise HTTPException(400, "Минимальная ставка — 500 GRAM")
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal = cur.fetchone()[0]
    if bal < data.bet: conn.close(); raise HTTPException(400, "Недостаточно GRAM!")

    cur.execute("SELECT item_type, rarity, quality_pct, sell_price, income_per_sec, is_verified, last_duel_at, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    my_item = cur.fetchone()
    if not my_item: conn.close(); raise HTTPException(400, "Выберите предмет из Сейфа!")
    itype, my_rar, my_q, sell_p, inc_p, is_ver, last_duel, is_st = my_item
    if is_st == 1: conn.close(); raise HTTPException(400, "Предмет в Холд-Банке!")
    cd_left = (int(last_duel or 0) + 120) - now
    if cd_left > 0: conn.close(); raise HTTPException(400, f"Перезарядка предмета ещё {cd_left} сек.")

    my_q = min(100, max(10, int(my_q or 90)))
    my_rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == my_rar), 0)
    opp_name = f"@{random.choice(REAL_CHAT_USERNAMES)}"
    opp_cand = fast_build_item_in_memory(itype or "username", my_rar_idx, 1.0)
    opp_tag = opp_cand["tag"]
    opp_q = random.randint(65, 98)

    my_power = 500 + my_q + (12 if is_ver else 0) + random.randint(-45, 45)
    opp_power = 500 + opp_q + random.randint(-42, 48)
    win = False if random.random() < 0.05 else (my_power >= opp_power)

    wear_loss = 2 if win else 5
    new_q = max(10, my_q - wear_loss)
    wear_ratio = new_q / max(15.0, float(my_q))
    new_sell = max(15, round(sell_p * wear_ratio))
    new_inc = max(0.1, round(inc_p * wear_ratio, 2))

    cur.execute("UPDATE usernames SET quality_pct = ?, sell_price = ?, income_per_sec = ?, last_duel_at = ? WHERE tag = ? AND owner_id = ?",
                (new_q, new_sell, new_inc, now, data.tag, data.user_id))

    if win:
        profit = round(data.bet * 0.90)
        cur.execute("UPDATE users SET balance = balance + ?, duel_wins = duel_wins + 1, q_duels = q_duels + 1, w_duels = COALESCE(w_duels,0) + 1, season_xp = season_xp + 20 WHERE tg_user_id = ?", (profit, data.user_id))
        msg = f"ПОБЕДА ({my_rar})! Твой {data.tag} ({my_power}) одолел {opp_tag} ({opp_power}) игрока {opp_name}! Выигрыш: +{profit:,} G! (Качество: {new_q}%)"
    else:
        cur.execute("UPDATE users SET balance = balance - ?, q_duels = q_duels + 1, w_duels = COALESCE(w_duels,0) + 1, season_xp = season_xp + 5 WHERE tg_user_id = ?", (data.bet, data.user_id))
        msg = f"Поражение! {opp_name} с {opp_tag} ({opp_power}) обошел твой {data.tag} ({my_power}). (Качество: {new_q}%)"

    conn.commit(); conn.close()
    return {"win": win, "new_q": new_q, "new_sell": new_sell, "message": msg}

CRAFT_COSTS = {"Common": 250, "Uncommon": 1200, "Rare": 5000, "Epic": 25000, "Legendary": 120000, "Mythic": 500000, "Luxury": 2000000}

@app.post("/api/craft")
def craft_items(data: ReqCraft):
    if len(data.tags) != 5: raise HTTPException(400, "Выберите ровно 5 предметов для верстака!")
    conn = get_db(); cur = conn.cursor()
    ph = ",".join("?" for _ in data.tags)
    cur.execute(f"SELECT tag, item_type, rarity, quality_pct, is_equipped, on_market, is_staked FROM usernames WHERE owner_id = ? AND tag IN ({ph})", [data.user_id, *data.tags])
    rows = cur.fetchall()
    if len(rows) != 5 or len({r[2] for r in rows}) > 1 or any(r[4] == 1 or r[5] == 1 or r[6] == 1 for r in rows):
        conn.close(); raise HTTPException(400, "Все 5 предметов должны быть свободны и одной редкости!")

    base_rar = rows[0][2]; itype = rows[0][1] or "username"
    avg_q = int(sum(min(100, (r[3] or 80)) for r in rows) / 5)
    crafted_q = min(100, avg_q + 5)  # Жесткий лок на 100%!

    rar_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == base_rar), -1)
    if rar_idx < 0 or rar_idx >= len(RARITIES) - 1: conn.close(); raise HTTPException(400, "Этот тир нельзя улучшить крафтом")
    cost = CRAFT_COSTS.get(base_rar, 2000)
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < cost: conn.close(); raise HTTPException(400, f"Нужно {cost:,} GRAM")

    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({ph})", [data.user_id, *data.tags])
    cur.execute("UPDATE users SET balance = balance - ?, q_crafts = q_crafts + 1, season_xp = season_xp + 15 WHERE tg_user_id = ?", (cost, data.user_id))
    if random.random() < 0.15:
        conn.commit(); conn.close()
        return {"burned": True, "message": "Контракт сорвался (15% риск)! 5 предметов сгорели в плавильне..."}

    now = int(time.time())
    cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory(itype, rar_idx + 1, 1.5, quality_override=crafted_q))
    cur.execute("INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,1,0,?)",
                (cand["tag"], cand["type"], data.user_id, cand["rarity"], min(100, cand["quality"]), cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
    conn.commit(); conn.close()
    return {"burned": False, "item": {"tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "q": min(100, cand["quality"]), "inc": cand["inc"], "sell": cand["sell"]}}

# ==========================================
# РЫНОК И ЗВЕЗДНЫЙ АУКЦИОН (СВОЯ СТАВКА + ПРОДАЖА ПРЯМО ИЗ СПИСКА)
# ==========================================
@app.post("/api/market/create")
def market_create(data: ReqMarketCreate):
    curr = "stars" if data.currency == "stars" else "gram"
    min_p = 5 if curr == "stars" else 100
    if data.price < min_p:
        raise HTTPException(400, f"Мин. цена: {min_p} {'⭐️' if curr=='stars' else 'GRAM'}")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, income_per_sec, num_multi, reasons, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row or row[5] == 1 or row[6] == 1 or row[7] == 1:
        conn.close(); raise HTTPException(400, "Снимите предмет с канала/банка перед выставлением!")
    itype, rar, inc, num_x, reas, _, _, _ = row
    now = int(time.time()); ends_at = now + (data.hours * 3600)
    cur.execute("UPDATE usernames SET on_market = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    cur.execute("""
        INSERT INTO market_lots (tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, seller_name, currency, is_auction, start_price, current_price, buyout_price, ends_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.tag, itype, rar, inc, num_x or 1.5, reas, data.user_id, data.username, curr, data.is_auction, data.price, data.price, round(data.price * 2.5), ends_at, now))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/market/interact")
def market_interact(data: ReqMarketInteract):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    settle_expired_auctions(cur)
    cur.execute("SELECT tag, item_type, rarity, income_per_sec, num_multi, reasons, seller_id, currency, is_auction, current_price, buyout_price, highest_bidder_id, bids_count, ends_at FROM market_lots WHERE lot_id = ?", (data.lot_id,))
    lot = cur.fetchone()
    if not lot: conn.close(); raise HTTPException(400, "Лот уже закрыт")
    tag, itype, rar, inc, num_x, reas, seller_id, curr, is_auc, cur_price, buyout, prev_bidder, bids_cnt, ends_at = lot
    curr = curr or "gram"
    if seller_id == data.user_id: conn.close(); raise HTTPException(400, "Это ваш собственный лот!")

    cur.execute("SELECT balance, stars_balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    my_bal, my_stars = cur.fetchone()
    my_stars = int(my_stars or 0)

    if is_auc == 0 or data.act == "buy":
        pay = cur_price if is_auc == 0 else buyout
        if curr == "stars":
            if my_stars < pay: conn.close(); raise HTTPException(400, f"Нужно {int(pay)} ⭐️ Stars на балансе!")
            if prev_bidder and prev_bidder > 0:
                cur.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE tg_user_id = ?", (int(cur_price), prev_bidder))
            cur.execute("UPDATE users SET stars_balance = stars_balance - ? WHERE tg_user_id = ?", (int(pay), data.user_id))
            if seller_id and seller_id > 0:
                cur.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE tg_user_id = ?", (max(1, int(pay * 0.95)), seller_id))
        else:
            if my_bal < pay: conn.close(); raise HTTPException(400, f"Нужно {int(pay):,} GRAM")
            if prev_bidder and prev_bidder > 0:
                cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder))
            cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (pay, data.user_id))
            if seller_id and seller_id > 0:
                cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (round(pay * 0.95, 2), seller_id))

        if itype == "nat_phone":
            cur.execute("UPDATE users SET national_phone = ? WHERE tg_user_id = ?", (tag, data.user_id))
        else:
            cur.execute("INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at) VALUES (?,?,?,?,95,?,?,?,?,0,0,1,0,?)",
                        (tag, itype, data.user_id, rar, inc, round(pay * 0.85, 0) if curr=='gram' else 500000, num_x or 1.5, reas, now))
        cur.execute("DELETE FROM market_lots WHERE lot_id = ?", (data.lot_id,))
        conn.commit(); conn.close()
        return {"status": "bought", "tag": tag}

    min_next = round(cur_price * 1.08) if bids_cnt > 0 else cur_price
    if curr == "stars" and bids_cnt > 0 and min_next <= cur_price:
        min_next = cur_price + 1
    new_bid = max(min_next, round(float(data.custom_bid or 0)))

    if curr == "stars":
        if my_stars < new_bid: conn.close(); raise HTTPException(400, f"Для ставки нужно {int(new_bid)} ⭐️ Stars!")
        if prev_bidder and prev_bidder > 0:
            cur.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE tg_user_id = ?", (int(cur_price), prev_bidder))
        cur.execute("UPDATE users SET stars_balance = stars_balance - ? WHERE tg_user_id = ?", (int(new_bid), data.user_id))
    else:
        if my_bal < new_bid: conn.close(); raise HTTPException(400, f"Для ставки нужно {int(new_bid):,} GRAM")
        if prev_bidder and prev_bidder > 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (cur_price, prev_bidder))
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (new_bid, data.user_id))

    cur.execute("UPDATE market_lots SET current_price = ?, highest_bidder_id = ?, highest_bidder_name = ?, bids_count = bids_count + 1, ends_at = ? WHERE lot_id = ?",
                (new_bid, data.user_id, data.username, max(ends_at, now + 60), data.lot_id))
    conn.commit(); conn.close()
    return {"status": "bid_placed", "new_price": new_bid}

# ==========================================
# АПГРЕЙДЕР, КОТЕЛ, ХОЛД-БАНК, ВЕРИФИКАЦИЯ, ДЕЙСТВИЯ
# ==========================================
UPGRADE_CHANCES = {2: 48, 3: 31, 5: 18, 10: 9}

@app.post("/api/minigame/upgrade")
def minigame_upgrade_item(data: ReqUpgradeItem):
    check_rate(data.user_id, 6, 2.0)
    if data.target_mult not in UPGRADE_CHANCES:
        raise HTTPException(400, "Выберите множитель: ×2, ×3, ×5 или ×10")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row or row[3] == 1 or row[4] == 1 or row[5] == 1:
        conn.close(); raise HTTPException(400, "Предмет должен быть свободен в Сейфе!")
    itype, rar, old_sell, _, _, _ = row

    chance_pct = UPGRADE_CHANCES[data.target_mult]
    win_sector_deg = (chance_pct / 100.0) * 360.0
    is_win = (random.random() * 100.0) <= chance_pct
    roll_deg = random.uniform(4.0, max(6.0, win_sector_deg - 4.0)) if is_win else random.uniform(win_sector_deg + 8.0, 352.0)

    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    if not is_win:
        cur.execute("UPDATE users SET season_xp = season_xp + 10 WHERE tg_user_id = ?", (data.user_id,))
        conn.commit(); conn.close()
        return {"win": False, "chance": chance_pct, "angle": round(roll_deg, 1), "message": f"Промах ({int(roll_deg)}°)! Предмет {data.tag} сгорел."}

    target_value = round(old_sell * data.target_mult)
    old_idx = next((i for i, r in enumerate(RARITIES) if r["name"] == rar), 0)
    step_up = 1 if data.target_mult == 2 else (2 if data.target_mult == 3 else (3 if data.target_mult == 5 else 4))
    new_idx = min(len(RARITIES) - 1, old_idx + step_up)
    now = int(time.time())
    cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory(itype or "username", new_idx, 2.0))
    cur.execute("""
        INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
    """, (cand["tag"], cand["type"], data.user_id, cand["rarity"], min(100, cand["quality"]), cand["inc"], target_value, cand["num_multi"], cand["reasons"], now))
    cur.execute("UPDATE users SET season_xp = season_xp + 35 WHERE tg_user_id = ?", (data.user_id,))
    conn.commit(); conn.close()
    return {"win": True, "chance": chance_pct, "angle": round(roll_deg, 1), "new_item": {"tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "sell": target_value, "inc": cand["inc"]}, "message": f"Апгрейд ×{data.target_mult} успешен! Получен {cand['tag']} ({target_value:,} G)!"}

@app.post("/api/minigame/jackpot")
def minigame_jackpot_wheel(data: ReqJackpotWheel):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
    row = cur.fetchone()
    if not row or row[1] == 1 or row[2] == 1 or row[3] == 1:
        conn.close(); raise HTTPException(400, "Выберите свободный предмет из Сейфа!")
    my_val = row[0]
    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    total_pot = my_val + round(my_val * random.uniform(0.55, 1.15)) + round(my_val * random.uniform(0.45, 1.05))
    my_chance = round((my_val / total_pot) * 100, 1)
    win = (random.random() * total_pot) <= my_val
    if win:
        payout = round(total_pot * 0.95)
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 30 WHERE tg_user_id = ?", (payout, data.user_id))
        msg = f"ДЖЕКПОТ КОТЛА ТВОЙ ({my_chance}%)! Получено +{payout:,} GRAM!"
    else:
        msg = f"Колесо остановилось на секторе соперника (Твой шанс был {my_chance}%)."
    conn.commit(); conn.close()
    return {"win": win, "chance": my_chance, "pot": total_pot, "message": msg}

STAKE_PLANS = {3: 0.12, 6: 0.25, 12: 0.45}

@app.post("/api/bank/stake")
def bank_stake_create(data: ReqBankStake):
    if data.hours not in STAKE_PLANS: raise HTTPException(400, "Доступно 3, 6 или 12 часов")
    rate_pct = STAKE_PLANS[data.hours]; now = int(time.time()); unlocks = now + (data.hours * 3600)
    conn = get_db(); cur = conn.cursor()
    if data.stake_type == "item":
        cur.execute("SELECT sell_price, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.tag, data.user_id))
        row = cur.fetchone()
        if not row or row[1] == 1 or row[2] == 1 or row[3] == 1:
            conn.close(); raise HTTPException(400, "Предмет должен быть свободен!")
        reward = round(row[0] * rate_pct)
        cur.execute("UPDATE usernames SET is_staked = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("INSERT INTO staked_deposits (user_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at, claimed, created_at) VALUES (?, 'item', ?, ?, ?, ?, ?, 0, ?)", (data.user_id, data.tag, row[0], reward, data.hours, unlocks, now))
    else:
        if data.amount < 5000: conn.close(); raise HTTPException(400, "Мин. вклад — 5,000 G")
        cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
        if cur.fetchone()[0] < data.amount: conn.close(); raise HTTPException(400, "Недостаточно GRAM!")
        reward = round(data.amount * rate_pct)
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
        cur.execute("INSERT INTO staked_deposits (user_id, stake_type, tag, principal_gram, reward_gram, hours, unlocks_at, claimed, created_at) VALUES (?, 'gram', 'Вклад GRAM', ?, ?, ?, ?, 0, ?)", (data.user_id, data.amount, reward, data.hours, unlocks, now))
    conn.commit(); conn.close()
    return {"status": "ok", "reward": reward}

@app.post("/api/bank/claim")
def bank_stake_claim(data: ReqBankClaim):
    now = int(time.time()); conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT stake_type, tag, principal_gram, reward_gram, unlocks_at, claimed FROM staked_deposits WHERE stake_id = ? AND user_id = ?", (data.stake_id, data.user_id))
    row = cur.fetchone()
    if not row or row[5] == 1: conn.close(); raise HTTPException(400, "Вклад не найден")
    if now < row[4]: conn.close(); raise HTTPException(400, f"Осталось ещё {int((row[4] - now)//60)+1} мин.")
    cur.execute("UPDATE staked_deposits SET claimed = 1 WHERE stake_id = ?", (data.stake_id,))
    if row[0] == "item":
        cur.execute("UPDATE usernames SET is_staked = 0 WHERE tag = ? AND owner_id = ?", (row[1], data.user_id))
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (row[3], data.user_id))
        msg = f"Предмет {row[1]} возвращен + дивиденды +{int(row[3]):,} GRAM!"
    else:
        cur.execute("UPDATE users SET balance = balance + ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (row[2] + row[3], data.user_id))
        msg = f"Вклад разморожен: +{int(row[2] + row[3]):,} GRAM!"
    conn.commit(); conn.close()
    return {"status": "ok", "message": msg}

@app.post("/api/tune_item")
def tune_verify_item(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT sell_price, income_per_sec, is_verified, reasons FROM usernames WHERE tag = ? AND owner_id = ? AND is_saved = 1", (data.key, data.user_id))
    row = cur.fetchone()
    if not row or row[2] == 1: conn.close(); raise HTTPException(400, "Уже верифицирован или не найден")
    cost = max(5000, round(row[0] * 0.35))
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < cost: conn.close(); raise HTTPException(400, f"Нужно {cost:,} GRAM")
    new_sell = round(row[0] * 1.50); new_inc = round(row[1] * 1.50, 2)
    new_reas = (row[3] + "|Верификация Fragment ×1,5") if row[3] else "Верификация Fragment ×1,5"
    cur.execute("UPDATE users SET balance = balance - ?, season_xp = season_xp + 30 WHERE tg_user_id = ?", (cost, data.user_id))
    cur.execute("UPDATE usernames SET sell_price = ?, income_per_sec = ?, is_verified = 1, reasons = ? WHERE tag = ? AND owner_id = ?", (new_sell, new_inc, new_reas, data.key, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "new_sell": new_sell, "new_inc": new_inc, "cost": cost}

@app.post("/api/action")
def tag_action(data: ReqAction):
    check_rate(data.user_id, 15, 2.0)
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT item_type, rarity, sell_price, is_saved, is_equipped, on_market, is_staked FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    t = cur.fetchone()
    if not t: conn.close(); raise HTTPException(400, "Предмет не найден")
    itype, rar, sell_price, is_saved, is_eq, on_mkt, is_st = t
    if on_mkt == 1 or is_st == 1: conn.close(); raise HTTPException(400, "Предмет занят на Рынке или в Холд-Банке!")

    used_slot = data.slot
    if data.action_type == "save":
        cur.execute("SELECT max_hold FROM users WHERE tg_user_id = ?", (data.user_id,))
        max_h = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1 AND on_market = 0", (data.user_id,))
        if cur.fetchone()[0] >= max_h: conn.close(); raise HTTPException(400, f"Сейф заполнен ({max_h} мест)!")
        cur.execute("UPDATE usernames SET is_saved = 1 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    elif data.action_type in ["sell", "sell_merchant"]:
        if is_eq == 1: conn.close(); raise HTTPException(400, "Сначала снимите предмет с канала!")
        final_price = sell_price
        hot = get_daily_hot_series()
        if hot["code"] in data.tag.lower(): final_price = round(final_price * (1.0 + hot["bonus_pct"] / 100.0))
        if data.action_type == "sell_merchant":
            merch = get_active_merchant_offer()
            if not merch["active"] or rar != merch["rarity"]: conn.close(); raise HTTPException(400, "Скупщик сейчас не принимает эту редкость!")
            final_price = round(final_price * merch["bonus_mult"])
        cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (final_price, data.user_id))
        conn.commit(); conn.close()
        return {"status": "ok", "sold_for": final_price}
    elif data.action_type == "equip":
        if itype == "number":
            used_slot = 99
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = 99", (data.user_id,))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = 99, equipped_at = ? WHERE tag = ? AND owner_id = ?", (now, data.tag, data.user_id))
        else:
            cur.execute("SELECT max_channels FROM users WHERE tg_user_id = ?", (data.user_id,))
            max_ch = cur.fetchone()[0]
            if not (data.slot and 1 <= data.slot <= max_ch):
                cur.execute("SELECT channel_slot FROM usernames WHERE owner_id = ? AND is_equipped = 1 AND channel_slot < 90", (data.user_id,))
                busy = {r[0] for r in cur.fetchall()}
                used_slot = next((s for s in range(1, max_ch + 1) if s not in busy), 1)
            cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE owner_id = ? AND channel_slot = ?", (data.user_id, used_slot))
            cur.execute("UPDATE usernames SET is_saved = 1, is_equipped = 1, channel_slot = ?, equipped_at = ? WHERE tag = ? AND owner_id = ?", (used_slot, now, data.tag, data.user_id))
    elif data.action_type == "unequip":
        cur.execute("UPDATE usernames SET is_equipped = 0, channel_slot = 0 WHERE tag = ? AND owner_id = ?", (data.tag, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "sold_for": sell_price, "slot": used_slot}

# ==========================================
# ПАСС 100 УРОВНЕЙ, СКИП УРОВНЯ ЗА STARS, ДНЯ/НЕДЕЛИ/АЧИВКИ/КОЛЛЕКЦИИ/КОЛЕСО
# ==========================================
@app.post("/api/pass/skip_level")
def skip_pass_level_with_stars(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT season_xp, stars_balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    s_xp, stars_b = cur.fetchone()
    stars_b = int(stars_b or 0)
    cur_lvl, cur_rem, req_xp = get_pass_level_info(s_xp or 0)
    if cur_lvl >= 100:
        conn.close(); raise HTTPException(400, "Вы уже достигли 100-го уровня Сезонного Пасса!")
    cost_stars = get_pass_skip_cost_stars(cur_lvl)
    if stars_b < cost_stars:
        conn.close(); raise HTTPException(400, f"Для пропуска уровня #{cur_lvl + 1} нужно {cost_stars} ⭐️ на счете!")
    needed_xp = max(1, req_xp - cur_rem)
    cur.execute("UPDATE users SET stars_balance = stars_balance - ?, season_xp = season_xp + ? WHERE tg_user_id = ?",
                (cost_stars, needed_xp, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "new_lvl": cur_lvl + 1, "spent_stars": cost_stars}

@app.post("/api/claim_reward")
def claim_quest_or_pass(data: ReqSimple):
    now = int(time.time())
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT q_spins, q_rare, q_crafts, q_duels, q_claimed,
               w_spins, w_cases, w_duels, w_claimed,
               season_xp, season_claimed, ach_stats, ach_claimed, unlocked_titles
        FROM users WHERE tg_user_id = ?
    """, (data.user_id,))
    (qs, qr, qc, qd, q_cl_raw, ws, wc, wd, w_cl_raw, s_xp, s_cl_raw, a_st_raw, a_cl_raw, unl_raw) = cur.fetchone()
    q_cl = json.loads(q_cl_raw or "[]"); w_cl = json.loads(w_cl_raw or "[]")
    s_cl = json.loads(s_cl_raw or "[]"); a_st = json.loads(a_st_raw or "{}")
    a_cl = json.loads(a_cl_raw or "[]"); unl_t = json.loads(unl_raw or '["Магнат"]')
    key = data.key; reward = 0; add_stars = 0; add_s_xp = 0; msg_extra = ""

    if key == "q1" and qs >= 20 and "q1" not in q_cl: reward = 35000; add_s_xp = 50; q_cl.append("q1")
    elif key == "q2" and qr >= 5 and "q2" not in q_cl: reward = 85000; add_s_xp = 50; q_cl.append("q2")
    elif key == "q3" and qc >= 1 and "q3" not in q_cl: reward = 65000; add_s_xp = 50; q_cl.append("q3")
    elif key == "q4" and (qd or 0) >= 3 and "q4" not in q_cl: reward = 95000; add_s_xp = 60; q_cl.append("q4")
    elif key == "q_all" and all(x in q_cl for x in ["q1", "q2", "q3"]) and "q_all" not in q_cl: reward = 350000; add_s_xp = 120; q_cl.append("q_all")
    # Недельные задания (х5-10 наград!)
    elif key == "w1" and (ws or 0) >= 300 and "w1" not in w_cl: reward = 1500000; add_s_xp = 250; w_cl.append("w1")
    elif key == "w2" and (wc or 0) >= 15 and "w2" not in w_cl: reward = 2500000; add_s_xp = 300; w_cl.append("w2")
    elif key == "w3" and (wd or 0) >= 25 and "w3" not in w_cl: reward = 3500000; add_stars = 10; add_s_xp = 400; w_cl.append("w3")
    elif key.startswith("pass_"):
        lvl = int(key.split("_")[1])
        cur_pass_lvl, _, _ = get_pass_level_info(s_xp or 0)
        if cur_pass_lvl >= lvl and key not in s_cl:
            p_rew = get_pass_reward_for_level(lvl)
            reward = p_rew.get("gram", 0)
            add_stars = p_rew.get("stars", 0)
            if p_rew["type"] == "mega_100":
                cur.execute("UPDATE users SET vip_until = GREATEST(vip_until, ?) + 43200, luck_multi = GREATEST(luck_multi, 5.0), luck_until = GREATEST(luck_until, ?) + 10800 WHERE tg_user_id = ?" if conn.is_pg else "UPDATE users SET vip_until = MAX(vip_until, ?) + 43200, luck_multi = MAX(luck_multi, 5.0), luck_until = MAX(luck_until, ?) + 10800 WHERE tg_user_id = ?", (now, now, data.user_id))
                if "СОТКА ПАССА" not in unl_t: unl_t.append("СОТКА ПАССА")
            elif p_rew["type"] == "blackout_pepe":
                cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory("gift", 8, 5.0, quality_override=100, force_blackout=True))
                cand["sell"] = random.randint(150000000, 950000000)
                cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,100,?,?,1.0,?,1,?)",
                            (cand["tag"], "gift", data.user_id, "Exclusive", cand["inc"], cand["sell"], cand["reasons"], now))
                msg_extra = f"Выпал {cand['tag']} ({cand['sell']:,} G)!"
            s_cl.append(key)
    elif key.startswith("ach_"):
        parts = key.split("_"); rar = parts[1]; target = int(parts[2])
        if a_st.get(rar, 0) >= target and key not in a_cl:
            reward = target * 45000; a_cl.append(key)
            if target >= 100:
                t_name = f"Властелин {rar}"
                if t_name not in unl_t: unl_t.append(t_name)
    else:
        conn.close(); raise HTTPException(400, "Условия не выполнены или награда уже получена")

    cur.execute("""
        UPDATE users SET balance = balance + ?, stars_balance = COALESCE(stars_balance,0) + ?, season_xp = season_xp + ?,
                         q_claimed = ?, w_claimed = ?, season_claimed = ?, ach_claimed = ?, unlocked_titles = ?
        WHERE tg_user_id = ?
    """, (reward, add_stars, add_s_xp, json.dumps(q_cl), json.dumps(w_cl), json.dumps(s_cl), json.dumps(a_cl), json.dumps(unl_t, ensure_ascii=False), data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward, "stars": add_stars, "extra": msg_extra}

@app.post("/api/claim_album")
def claim_album(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT albums_claimed, unlocked_titles FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    claimed = json.loads(row[0] or "[]")
    unl_t = json.loads(row[1] or '["Магнат"]')
    if data.key in claimed: conn.close(); raise HTTPException(400, "Коллекция уже собрана!")
    cur.execute("SELECT tag, item_type, rarity, is_verified FROM usernames WHERE owner_id = ? AND is_saved = 1", (data.user_id,))
    my_tags = cur.fetchall()

    reward = 0
    if data.key == "alb_numbers":
        cnt = sum(1 for t in my_tags if t[1] == "number")
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 номера +888 ({cnt}/3)")
        reward = 350000
    elif data.key == "alb_gifts":
        cnt = sum(1 for t in my_tags if t[1] == "gift")
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 NFT-Подарка ({cnt}/3)")
        reward = 450000
    elif data.key == "alb_blackout":
        cnt = sum(1 for t in my_tags if "[BLACKOUT]" in (t[0] or ""))
        if cnt < 2: conn.close(); raise HTTPException(400, f"Нужно 2 подарка на Чёрном фоне [BLACKOUT] ({cnt}/2)")
        reward = 3500000
        if "BLACKOUT LOVER" not in unl_t: unl_t.append("BLACKOUT LOVER")
    elif data.key == "alb_verified":
        cnt = sum(1 for t in my_tags if (t[3] or 0) == 1)
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 верифицированных предмета ({cnt}/3)")
        reward = 1200000
    elif data.key == "alb_epic":
        cnt = sum(1 for t in my_tags if t[2] in ["Epic", "Legendary", "Mythic", "Luxury", "Ultra-Mythic", "Exclusive", "Divine"])
        if cnt < 5: conn.close(); raise HTTPException(400, f"Нужно 5 предметов Epic+ ({cnt}/5)")
        reward = 800000
    elif data.key == "alb_short":
        cnt = sum(1 for t in my_tags if t[1] == "username" and len(t[0]) <= 5)
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 коротких @username до 4 букв ({cnt}/3)")
        reward = 2500000
    elif data.key == "alb_luxury":
        cnt = sum(1 for t in my_tags if t[2] in ["Luxury", "Ultra-Mythic", "Exclusive", "Divine"])
        if cnt < 3: conn.close(); raise HTTPException(400, f"Нужно 3 предмета Luxury+ ({cnt}/3)")
        reward = 12000000
        if "КОЛЛЕКЦИОНЕР" not in unl_t: unl_t.append("КОЛЛЕКЦИОНЕР")
    else:
        conn.close(); raise HTTPException(400, "Неизвестная коллекция")

    claimed.append(data.key)
    cur.execute("UPDATE users SET balance = balance + ?, albums_claimed = ?, unlocked_titles = ?, season_xp = season_xp + 100 WHERE tg_user_id = ?",
                (reward, json.dumps(claimed), json.dumps(unl_t, ensure_ascii=False), data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward}

# КОЛЕСО ФОРТУНЫ С МАСШТАБИРОВАНИЕМ ОТ УРОВНЯ ИГРОКА!
@app.post("/api/wheel_spin")
def spin_wheel(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT last_wheel, level FROM users WHERE tg_user_id = ?", (data.user_id,))
    lw, lvl = cur.fetchone()
    if (now - lw) < 1800: conn.close(); raise HTTPException(400, "Колесо доступно раз в 30 минут!")
    lvl_mult = max(1, int(1 + (lvl - 1) * 0.35))
    prizes = [
        {"idx": 0, "title": f"{(15000 * lvl_mult):,} GRAM", "type": "coins", "val": 15000 * lvl_mult, "w": 340},
        {"idx": 1, "title": f"{(35000 * lvl_mult):,} GRAM", "type": "coins", "val": 35000 * lvl_mult, "w": 250},
        {"idx": 2, "title": "Удача ×2 (1 час)", "type": "luck", "val": 3600, "w": 130},
        {"idx": 3, "title": f"{(75000 * lvl_mult):,} GRAM", "type": "coins", "val": 75000 * lvl_mult, "w": 110},
        {"idx": 4, "title": "NFT-Подарок (Rare+)", "type": "gift", "val": "Rare", "w": 85},
        {"idx": 5, "title": f"{(200000 * lvl_mult):,} GRAM", "type": "coins", "val": 200000 * lvl_mult, "w": 45},
        {"idx": 6, "title": "Номер +888 (Rare+)", "type": "num", "val": "Rare", "w": 25},
        {"idx": 7, "title": f"ДЖЕКПОТ {(2500000 * lvl_mult):,} G", "type": "coins", "val": 2500000 * lvl_mult, "w": 15}
    ]
    tot = sum(p["w"] for p in prizes); r = random.random() * tot
    picked = prizes[0]
    for p in prizes:
        if r < p["w"]: picked = p; break
        r -= p["w"]
    if picked["type"] == "coins":
        cur.execute("UPDATE users SET balance = balance + ?, last_wheel = ?, season_xp = season_xp + 15 WHERE tg_user_id = ?", (picked["val"], now, data.user_id))
    elif picked["type"] == "luck":
        cur.execute("UPDATE users SET luck_multi = GREATEST(luck_multi, 2.0), luck_until = GREATEST(luck_until, ?) + 3600, last_wheel = ? WHERE tg_user_id = ?" if conn.is_pg else "UPDATE users SET luck_multi = MAX(luck_multi, 2.0), luck_until = MAX(luck_until, ?) + 3600, last_wheel = ? WHERE tg_user_id = ?", (now, now, data.user_id))
    elif picked["type"] == "gift":
        r_idx = 3 if lvl >= 25 else 2
        cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory("gift", r_idx, 1.5))
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)", (cand["tag"], "gift", data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], 1.0, cand["reasons"], now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    elif picked["type"] == "num":
        r_idx = 3 if lvl >= 25 else 2
        cand = ensure_unique_tag_clean(cur, fast_build_item_in_memory("number", r_idx, 1.5))
        cur.execute("INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_saved, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)", (cand["tag"], "number", data.user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
        cur.execute("UPDATE users SET last_wheel = ? WHERE tg_user_id = ?", (now, data.user_id))
    conn.commit(); conn.close()
    return {"prize_idx": picked["idx"], "title": picked["title"]}

# ==========================================
# МАГАЗИН ЗА БАЛАНС STARS + ПОПОЛНЕНИЕ STARS + ДОНАТ-ПРЕФИКС «БОГАТЫЙ»
# ==========================================
PRICES = {
    "topup_stars_50":     {"title": "⭐️ Пополнение: +50 Stars на счет",   "price": 50},
    "topup_stars_200":    {"title": "⭐️ Пополнение: +200 Stars на счет",  "price": 200},
    "topup_stars_500":    {"title": "⭐️ Пополнение: +500 Stars (+50 бонус)", "price": 500},
    "prefix_rich":        {"title": "💎 Эксклюзивный префикс «БОГАТЫЙ»",   "price": 149},
    "spin_10_stars":      {"title": "⚡ 10× Прокрутов сразу (Rare+)",       "price": 150},
    "spin_25_stars":      {"title": "🔥 25× Мега-Прокрутов (Epic+)",       "price": 219},
    "ai_holding":         {"title": "🤖 AI-Нейросеть Каналов (×1.5)",       "price": 129},
    "vip_pass":           {"title": "👑 VIP Game Pass (30 дней)",          "price": 89},
    "luck_x2_1h":         {"title": "🍀 Буст Удачи ×2 (1 час)",            "price": 19},
    "luck_x5_2h":         {"title": "🔥 Мега Удача ×5 (2 часа)",           "price": 49},
    "hold_plus_50":       {"title": "💼 +50 слотов в Хранилище",           "price": 45},
    "channel_slot":       {"title": "📢 Новый слот Канала",                "price": 59},
    "coins_10m":          {"title": "🪙 5,000,000 GRAM Магната",           "price": 35},
    "coins_100m":         {"title": "💰 50,000,000 GRAM Империи",          "price": 99},
    "case_stars_lite":    {"title": "⭐️ Звездный Ларец (Бокс)",            "price": 29},
    "case_stars_founder": {"title": "👑 Бокс Основателя (Mythic+)",        "price": 99},
    "case_stars_divine":  {"title": "💎 Божественный Сундук Дурова",       "price": 249}
}

def apply_donate_product(cur, user_id: int, p: str, itype: str = "username"):
    now = int(time.time())
    drops = []
    case_res = None
    if p == "topup_stars_50":
        cur.execute("UPDATE users SET stars_balance = COALESCE(stars_balance,0) + 50 WHERE tg_user_id = ?", (user_id,))
    elif p == "topup_stars_200":
        cur.execute("UPDATE users SET stars_balance = COALESCE(stars_balance,0) + 200 WHERE tg_user_id = ?", (user_id,))
    elif p == "topup_stars_500":
        cur.execute("UPDATE users SET stars_balance = COALESCE(stars_balance,0) + 550 WHERE tg_user_id = ?", (user_id,))
    elif p == "prefix_rich":
        cur.execute("SELECT unlocked_titles FROM users WHERE tg_user_id = ?", (user_id,))
        unl = json.loads(cur.fetchone()[0] or '["Магнат"]')
        if "БОГАТЫЙ" not in unl: unl.append("БОГАТЫЙ")
        cur.execute("UPDATE users SET custom_title = 'БОГАТЫЙ', nick_color = '#fbbf24', unlocked_titles = ? WHERE tg_user_id = ?", (json.dumps(unl, ensure_ascii=False), user_id))
    elif p == "spin_10_stars":
        drops, _, _, _ = execute_spins_internal(cur, user_id, itype, "tier_2", 10, 0.0, 0)
    elif p == "spin_25_stars":
        drops, _, _, _ = execute_spins_internal(cur, user_id, itype, "tier_3", 25, 0.0, 0)
    elif p in ["case_stars_lite", "case_stars_founder", "case_stars_divine"]:
        cand, tape = roll_case_drop_fast(cur, p, 2.5, user_id)
        cur.execute("""
            INSERT OR IGNORE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 0, ?)
        """, (cand["tag"], cand["type"], user_id, cand["rarity"], cand["quality"], cand["inc"], cand["sell"], cand["num_multi"], cand["reasons"], now))
        case_res = {"winner": {"tag": cand["tag"], "type": cand["type"], "rarity": cand["rarity"], "rar_idx": cand["rar_idx"], "q": cand["quality"], "inc": cand["inc"], "sell": cand["sell"], "num_x": cand["num_multi"], "reasons": cand["reasons"].split("|")}, "tape": tape}
    elif p == "ai_holding":
        cur.execute("UPDATE users SET ai_boost = 1 WHERE tg_user_id = ?", (user_id,))
    elif p == "vip_pass":
        cur.execute("UPDATE users SET vip_until = GREATEST(vip_until, ?) + 2592000, max_hold = max_hold + 50, balance = balance + 5000000 WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET vip_until = MAX(vip_until, ?) + 2592000, max_hold = max_hold + 50, balance = balance + 5000000 WHERE tg_user_id = ?", (now, user_id))
    elif p == "luck_x2_1h":
        cur.execute("UPDATE users SET luck_multi = GREATEST(luck_multi, 2.0), luck_until = GREATEST(luck_until, ?) + 3600 WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET luck_multi = MAX(luck_multi, 2.0), luck_until = MAX(luck_until, ?) + 3600 WHERE tg_user_id = ?", (now, now, user_id))
    elif p == "luck_x5_2h":
        cur.execute("UPDATE users SET luck_multi = GREATEST(luck_multi, 5.0), luck_until = GREATEST(luck_until, ?) + 7200 WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET luck_multi = MAX(luck_multi, 5.0), luck_until = MAX(luck_until, ?) + 7200 WHERE tg_user_id = ?", (now, now, user_id))
    elif p == "hold_plus_50":
        cur.execute("UPDATE users SET max_hold = max_hold + 50 WHERE tg_user_id = ?", (user_id,))
    elif p == "channel_slot":
        cur.execute("UPDATE users SET max_channels = LEAST(15, max_channels + 1) WHERE tg_user_id = ?" if cur.is_pg else "UPDATE users SET max_channels = MIN(15, max_channels + 1) WHERE tg_user_id = ?", (user_id,))
    elif p == "coins_10m":
        cur.execute("UPDATE users SET balance = balance + 5000000 WHERE tg_user_id = ?", (user_id,))
    elif p == "coins_100m":
        cur.execute("UPDATE users SET balance = balance + 50000000 WHERE tg_user_id = ?", (user_id,))
    return drops, case_res

@app.post("/api/stars/spend_balance")
def spend_internal_stars(data: ReqSimple):
    parts = data.key.split(":")
    p = parts[0]
    itype = parts[1] if len(parts) > 1 else "username"
    prod = PRICES.get(p)
    if not prod or p.startswith("topup_"):
        raise HTTPException(400, "Товар не найден")
    cost_s = prod["price"]
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT stars_balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    sb = int(cur.fetchone()[0] or 0)
    if sb < cost_s:
        conn.close(); raise HTTPException(400, f"Недостаточно Stars на балансе ({sb}/{cost_s} ⭐️)! Пополните счет Stars.")
    cur.execute("UPDATE users SET stars_balance = stars_balance - ? WHERE tg_user_id = ?", (cost_s, data.user_id))
    drops, case_res = apply_donate_product(cur, data.user_id, p, itype)
    conn.commit(); conn.close()
    return {"status": "ok", "drops": drops, "case_res": case_res, "spent": cost_s}

@app.get("/api/invoice")
async def get_invoice(payload: str):
    product = PRICES.get(payload)
    if not product: raise HTTPException(400, "Товар не найден")
    link = await bot.create_invoice_link(
        title=product["title"], description="Покупка в MintTags: Global Empire",
        payload=payload, currency="XTR",
        prices=[LabeledPrice(label=product["title"], amount=product["price"])]
    )
    return {"invoice_link": link}

@app.post("/api/activate_donate")
def activate_donate(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    parts = data.key.split(":")
    p = parts[0]
    itype = parts[1] if len(parts) > 1 else "username"
    stars_spent = PRICES.get(p, {}).get("price", 0)

    cur.execute("SELECT ref_by FROM users WHERE tg_user_id = ?", (data.user_id,))
    r_row = cur.fetchone()
    if r_row and r_row[0] and stars_spent > 0:
        ref_stars = max(1, int(stars_spent * 0.15))
        cur.execute("UPDATE users SET contrib_stars = contrib_stars + ?, stars_balance = COALESCE(stars_balance,0) + ? WHERE tg_user_id = ?", (ref_stars, ref_stars, r_row[0]))

    drops, case_res = apply_donate_product(cur, data.user_id, p, itype)
    conn.commit(); conn.close()
    return {"status": "ok", "drops": drops, "case_res": case_res}

# ==========================================
# ПРОЧИЕ ЭНДПОИНТЫ (КЛАНЫ, МУЗЕЙ, ЛОТЕРЕЯ, ШРЕДЕР, VIP-КАСТОМИЗАЦИЯ, ПРОМО)
# ==========================================
@app.get("/api/clan/members/{clan_id}")
def clan_get_members(clan_id: str):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT name, owner_id, level, treasury FROM clans WHERE clan_id = ?", (clan_id,))
    c_info = cur.fetchone()
    if not c_info: conn.close(); raise HTTPException(404, "Клан не найден")
    cur.execute("SELECT tg_user_id, username, level, clan_contrib FROM users WHERE clan_id = ? ORDER BY clan_contrib DESC LIMIT 100", (clan_id,))
    members = [{"uid": r[0], "username": r[1] or "Игрок", "level": r[2], "contrib": round(r[3] or 0.0)} for r in cur.fetchall()]
    conn.close()
    return {"name": c_info[0], "owner_id": c_info[1], "level": c_info[2], "treasury": round(c_info[3]), "members": members}

@app.post("/api/clan/kick")
def clan_kick_member(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT owner_id FROM clans WHERE clan_id = ?", (data.clan_id,))
    row = cur.fetchone()
    if not row or row[0] != data.user_id or data.target_uid == data.user_id:
        conn.close(); raise HTTPException(403, "Ошибка доступа")
    cur.execute("UPDATE users SET clan_id = NULL, clan_contrib = 0 WHERE tg_user_id = ? AND clan_id = ?", (data.target_uid, data.clan_id))
    cur.execute("UPDATE clans SET members_count = GREATEST(1, members_count - 1) WHERE clan_id = ?" if conn.is_pg else "UPDATE clans SET members_count = MAX(1, members_count - 1) WHERE clan_id = ?", (data.clan_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/delete")
def clan_delete_full(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT owner_id FROM clans WHERE clan_id = ?", (data.clan_id,))
    row = cur.fetchone()
    if not row or row[0] != data.user_id: conn.close(); raise HTTPException(403, "Только владелец может удалить клан!")
    cur.execute("UPDATE users SET clan_id = NULL, clan_contrib = 0 WHERE clan_id = ?", (data.clan_id,))
    cur.execute("DELETE FROM clans WHERE clan_id = ?", (data.clan_id,))
    conn.commit(); conn.close()
    return {"status": "deleted"}

@app.post("/api/clan/create")
def clan_create(data: ReqClanCreate):
    clean_name = data.name.strip()
    if len(clean_name) < 3 or len(clean_name) > 16: raise HTTPException(400, "От 3 до 16 символов!")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, cur_clan = cur.fetchone()
    if cur_clan or bal < 1000000.0: conn.close(); raise HTTPException(400, "Нужно 1,000,000 G и не состоять в клане!")
    cid = f"clan_{data.user_id}_{int(time.time())}"
    cur.execute("UPDATE users SET balance = balance - 1000000.0, clan_id = ?, clan_contrib = 0 WHERE tg_user_id = ?", (cid, data.user_id))
    cur.execute("INSERT INTO clans (clan_id, name, owner_id, level, treasury, members_count, max_members, created_at) VALUES (?, ?, ?, 1, 0.0, 1, 100, ?)", (cid, clean_name, data.user_id, int(time.time())))
    conn.commit(); conn.close()
    return {"status": "ok", "clan_id": cid}

@app.post("/api/clan/join")
def clan_join(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    old_c = cur.fetchone()[0]
    if old_c:
        cur.execute("UPDATE clans SET members_count = GREATEST(0, members_count - 1) WHERE clan_id = ?" if conn.is_pg else "UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (old_c,))
    cur.execute("UPDATE clans SET members_count = members_count + 1 WHERE clan_id = ?", (data.clan_id,))
    cur.execute("UPDATE users SET clan_id = ?, clan_contrib = 0 WHERE tg_user_id = ?", (data.clan_id, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/leave")
def clan_leave(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    if row and row[0]:
        cur.execute("UPDATE clans SET members_count = GREATEST(0, members_count - 1) WHERE clan_id = ?" if conn.is_pg else "UPDATE clans SET members_count = MAX(0, members_count - 1) WHERE clan_id = ?", (row[0],))
        cur.execute("UPDATE users SET clan_id = NULL, clan_contrib = 0 WHERE tg_user_id = ?", (data.user_id,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/clan/donate")
def clan_donate(data: ReqClanAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, clan_id FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, cid = cur.fetchone()
    if not cid or bal < data.amount: conn.close(); raise HTTPException(400, "Недостаточно средств")
    cur.execute("UPDATE users SET balance = balance - ?, clan_contrib = clan_contrib + ? WHERE tg_user_id = ?", (data.amount, data.amount, data.user_id))
    cur.execute("SELECT level, treasury FROM clans WHERE clan_id = ?", (cid,))
    lvl, tr = cur.fetchone()
    new_tr = tr + data.amount; new_lvl = lvl
    while new_tr >= new_lvl * 250000.0:
        new_tr -= new_lvl * 250000.0; new_lvl += 1
    cur.execute("UPDATE clans SET level = ?, treasury = ? WHERE clan_id = ?", (new_lvl, new_tr, cid))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/museum/set")
def museum_set_showcase(data: ReqMuseumSet):
    clean_tags = data.tags[:3]
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET museum_tags = ? WHERE tg_user_id = ?", (json.dumps(clean_tags), data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "museum_tags": clean_tags}

@app.post("/api/museum/like")
def museum_like_player(data: ReqSimple):
    target_uid = int(data.key or 0)
    if target_uid == data.user_id: raise HTTPException(400, "Нельзя лайкнуть самого себя!")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT liked_users FROM users WHERE tg_user_id = ?", (data.user_id,))
    liked = json.loads(cur.fetchone()[0] or "[]")
    if target_uid in liked: conn.close(); raise HTTPException(400, "Вы уже выразили респект этому магнату!")
    liked.append(target_uid)
    cur.execute("UPDATE users SET liked_users = ? WHERE tg_user_id = ?", (json.dumps(liked), data.user_id))
    cur.execute("UPDATE users SET museum_likes = museum_likes + 1 WHERE tg_user_id = ?", (target_uid,))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/lottery/buy")
def lottery_buy_tickets(data: ReqLotteryBuy):
    cnt = max(1, min(100, data.count)); cost = cnt * 10000.0
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, lottery_tickets, username FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, my_tix, uname = cur.fetchone()
    if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {int(cost):,} GRAM!")
    LOTTERY_STATE["pot"] += cost; new_tix = (my_tix or 0) + cnt
    won_jackpot = False; win_sum = 0
    if random.random() < min(0.25, cnt * 0.015):
        won_jackpot = True; win_sum = round(LOTTERY_STATE["pot"])
        LOTTERY_STATE["last_winner"] = uname or "Магнат"; LOTTERY_STATE["last_win_amount"] = win_sum
        LOTTERY_STATE["pot"] = 1000000.0; new_tix = 0
    new_bal = round(bal - cost + win_sum, 2)
    cur.execute("UPDATE users SET balance = ?, lottery_tickets = ?, season_xp = season_xp + ? WHERE tg_user_id = ?", (new_bal, new_tix, cnt * 5, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "won_jackpot": won_jackpot, "win_sum": win_sum, "my_tickets": new_tix, "pot": LOTTERY_STATE["pot"], "balance": new_bal}

@app.post("/api/shredder/crush")
def shredder_crush_items(data: ReqShredder):
    if not data.tags: raise HTTPException(400, "Выберите предмет!")
    conn = get_db(); cur = conn.cursor()
    ph = ",".join("?" for _ in data.tags)
    cur.execute(f"SELECT tag, rarity FROM usernames WHERE owner_id = ? AND is_saved = 1 AND is_equipped = 0 AND on_market = 0 AND is_staked = 0 AND tag IN ({ph})", [data.user_id, *data.tags])
    rows = cur.fetchall()
    if not rows: conn.close(); raise HTTPException(400, "Свободный предмет не найден!")
    gears_gain = sum((next((i for i, r in enumerate(RARITIES) if r["name"] == rar), 0) + 1) * 5 for _, rar in rows)
    del_tags = [r[0] for r in rows]
    ph_d = ",".join("?" for _ in del_tags)
    cur.execute(f"DELETE FROM usernames WHERE owner_id = ? AND tag IN ({ph_d})", [data.user_id, *del_tags])
    cur.execute("UPDATE users SET gears = gears + ? WHERE tg_user_id = ?", (gears_gain, data.user_id))
    cur.execute("SELECT gears FROM users WHERE tg_user_id = ?", (data.user_id,))
    tot_gears = cur.fetchone()[0]
    conn.commit(); conn.close()
    return {"status": "ok", "gained": gears_gain, "gears": tot_gears}

@app.post("/api/shredder/buy")
def shredder_buy_blackmarket(data: ReqShredder):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT gears FROM users WHERE tg_user_id = ?", (data.user_id,))
    gears = cur.fetchone()[0] or 0
    if data.shop_item == "repair_kit":
        if gears < 25: conn.close(); raise HTTPException(400, "Нужно 25 Шестеренок!")
        cur.execute("UPDATE users SET gears = gears - 25, repair_kits = repair_kits + 1 WHERE tg_user_id = ?", (data.user_id,))
        msg = "Куплен 100% Ремкомплект! Он восстанавливает износ предмета до 100% и возвращает полную цену и доход."
    elif data.shop_item == "lockpick":
        if gears < 40: conn.close(); raise HTTPException(400, "Нужно 40 Шестеренок!")
        cur.execute("UPDATE users SET gears = gears - 40, lockpicks = lockpicks + 1 WHERE tg_user_id = ?", (data.user_id,))
        msg = "Куплена Мастер-Отмычка для мгновенного взлома Сейфа Дурова!"
    else:
        conn.close(); raise HTTPException(400, "Товар не найден")
    conn.commit(); conn.close()
    return {"status": "ok", "message": msg}

@app.post("/api/profile/customize")
def customize_vip_profile(data: ReqCustomize):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, unlocked_titles FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, unl_raw = cur.fetchone()
    unl = json.loads(unl_raw or '["Магнат"]')
    clean_title = (data.custom_title or "Магнат").strip()[:18]
    # Если выбирает уже открытый префикс из коллекции — бесплатно, иначе кастом за 50M G
    if clean_title not in unl:
        if bal < VIP_STYLE_COST_GRAM:
            conn.close(); raise HTTPException(400, f"Смена на кастомный VIP-титул стоит {int(VIP_STYLE_COST_GRAM):,} GRAM!")
        cur.execute("UPDATE users SET balance = balance - ?, nick_color = ?, custom_title = ?, profile_frame = ? WHERE tg_user_id = ?",
                    (VIP_STYLE_COST_GRAM, data.nick_color, clean_title, data.profile_frame, data.user_id))
    else:
        cur.execute("UPDATE users SET nick_color = ?, custom_title = ?, profile_frame = ? WHERE tg_user_id = ?",
                    (data.nick_color, clean_title, data.profile_frame, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/contract/fulfill")
def fulfill_vip_contract(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT contracts_done FROM users WHERE tg_user_id = ?", (data.user_id,))
    done_list = json.loads(cur.fetchone()[0] or "[]")
    if data.key in done_list: conn.close(); raise HTTPException(400, "Уже выполнен сегодня!")
    c_obj = next((c for c in get_daily_vip_contracts() if c["id"] == data.key), None)
    if not c_obj: conn.close(); raise HTTPException(400, "Контракт не найден")
    cur.execute("SELECT tag, sell_price FROM usernames WHERE owner_id = ? AND item_type = ? AND rarity = ? AND is_saved = 1 AND is_equipped = 0 AND on_market = 0 AND is_staked = 0 LIMIT 1", (data.user_id, c_obj["req_type"], c_obj["req_rar"]))
    item = cur.fetchone()
    if not item: conn.close(); raise HTTPException(400, f"В Сейфе нет свободного {c_obj['req_type']} ({c_obj['req_rar']})!")
    payout = round(item[1] * c_obj["mult"] + c_obj["flat_bonus"]); done_list.append(data.key)
    cur.execute("DELETE FROM usernames WHERE tag = ? AND owner_id = ?", (item[0], data.user_id))
    cur.execute("UPDATE users SET balance = balance + ?, contracts_done = ?, season_xp = season_xp + 60 WHERE tg_user_id = ?", (payout, json.dumps(done_list), data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok", "tag": item[0], "payout": payout}

@app.post("/api/checks/create")
def create_gift_check(data: ReqCheckCreate):
    if data.amount < 5000: raise HTTPException(400, "Мин. сумма чека — 5,000 G")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE tg_user_id = ?", (data.user_id,))
    if cur.fetchone()[0] < data.amount: conn.close(); raise HTTPException(400, "Недостаточно GRAM!")
    code = f"CHK-{random.randint(1000,9999)}-{random.choice(['TON','VIP','MINT','GOLD'])}"
    cur.execute("UPDATE users SET balance = balance - ? WHERE tg_user_id = ?", (data.amount, data.user_id))
    cur.execute("INSERT INTO gift_checks (code, creator_id, amount, claimed_by, created_at) VALUES (?, ?, ?, NULL, ?)", (code, data.user_id, data.amount, int(time.time())))
    conn.commit(); conn.close()
    return {"code": code, "amount": data.amount}

@app.post("/api/minigame/vault")
def minigame_vault(data: ReqVaultHack):
    conn = get_db(); cur = conn.cursor(); now = int(time.time())
    cur.execute("SELECT last_vault, level, lockpicks FROM users WHERE tg_user_id = ?", (data.user_id,))
    lv, lvl, picks = cur.fetchone()
    used_pick = False
    if data.use_lockpick == 1 and (picks or 0) > 0:
        cur.execute("UPDATE users SET lockpicks = lockpicks - 1 WHERE tg_user_id = ?", (data.user_id,)); used_pick = True
    elif (now - (lv or 0)) < 3600:
        conn.close(); raise HTTPException(400, f"Доступно через {int((3600 - (now - (lv or 0))) // 60) + 1} мин.")
    win_cell = data.cell if used_pick else random.randint(1, 3)
    prize = (45000 if data.cell == win_cell else 6000) * lvl
    cur.execute("UPDATE users SET balance = balance + ?, last_vault = ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (prize, now, data.user_id))
    conn.commit(); conn.close()
    return {"message": f"Взломано: +{prize:,} GRAM!", "win_cell": win_cell}

PROMO_CODES = {"MINTTAGS": {"gram": 50000}, "DUROV": {"gram": 75000}, "888": {"gram": 100000}}

@app.post("/api/promo")
def activate_promo(data: ReqSimple):
    code = (data.key or "").strip().upper()
    conn = get_db(); cur = conn.cursor()
    if code.startswith("CHK-"):
        cur.execute("SELECT amount, claimed_by FROM gift_checks WHERE code = ?", (code,))
        chk = cur.fetchone()
        if not chk or chk[1] is not None: conn.close(); raise HTTPException(400, "Чек не найден или уже активирован!")
        cur.execute("UPDATE gift_checks SET claimed_by = ? WHERE code = ?", (data.user_id, code))
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (chk[0], data.user_id))
        conn.commit(); conn.close()
        return {"reward": chk[0], "code": code}
    if code not in PROMO_CODES: conn.close(); raise HTTPException(400, "Промокод не найден!")
    cur.execute("SELECT promos_used FROM users WHERE tg_user_id = ?", (data.user_id,))
    used = json.loads(cur.fetchone()[0] or "[]")
    if code in used: conn.close(); raise HTTPException(400, "Уже активирован!")
    used.append(code); rew = PROMO_CODES[code]["gram"]
    cur.execute("UPDATE users SET balance = balance + ?, promos_used = ? WHERE tg_user_id = ?", (rew, json.dumps(used), data.user_id))
    conn.commit(); conn.close()
    return {"reward": rew, "code": code}

DAILY_REWARDS = [15000, 35000, 75000, 150000, 300000, 600000, 1500000]

@app.post("/api/daily_gift")
def claim_daily(data: ReqSimple):
    conn = get_db(); cur = conn.cursor(); now = int(time.time())
    cur.execute("SELECT daily_streak, last_daily, vip_until FROM users WHERE tg_user_id = ?", (data.user_id,))
    streak, last_d, vip_u = cur.fetchone()
    if (now - last_d) < 86400: conn.close(); raise HTTPException(400, "Подарок уже получен сегодня!")
    if (now - last_d) > 172800: streak = 0
    reward = DAILY_REWARDS[streak % 7]; new_streak = (streak % 7) + 1
    new_vip = max(now, vip_u or 0) + 86400 if new_streak == 7 else (vip_u or 0)
    cur.execute("UPDATE users SET balance = balance + ?, daily_streak = ?, last_daily = ?, vip_until = ?, season_xp = season_xp + 25 WHERE tg_user_id = ?", (reward, new_streak, now, new_vip, data.user_id))
    conn.commit(); conn.close()
    return {"reward": reward, "day": new_streak, "vip_bonus": new_streak == 7}

@app.post("/api/upgrade_mgr")
def upgrade_manager(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, smm_lvl, buyer_lvl FROM users WHERE tg_user_id = ?", (data.user_id,))
    bal, smm, buyer = cur.fetchone()
    if data.key == "smm":
        if smm >= MAX_SMM_LVL: conn.close(); raise HTTPException(400, "Макс. уровень СММ!")
        cost = get_smm_upgrade_cost(smm)
        if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {int(cost):,} GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, smm_lvl = smm_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    else:
        if buyer >= MAX_BUYER_LVL: conn.close(); raise HTTPException(400, "Макс. уровень Байера!")
        cost = get_buyer_upgrade_cost(buyer)
        if bal < cost: conn.close(); raise HTTPException(400, f"Нужно {int(cost):,} GRAM")
        cur.execute("UPDATE users SET balance = balance - ?, buyer_lvl = buyer_lvl + 1 WHERE tg_user_id = ?", (cost, data.user_id))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.post("/api/toggle_notify_merchant")
def toggle_notify_merchant(data: ReqSimple):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT notify_merchant FROM users WHERE tg_user_id = ?", (data.user_id,))
    row = cur.fetchone()
    new_val = 0 if (row and row[0] == 1) else 1
    cur.execute("UPDATE users SET notify_merchant = ? WHERE tg_user_id = ?", (new_val, data.user_id))
    conn.commit(); conn.close()
    return {"notify_merchant": new_val}

# ==========================================
# СЕКРЕТНАЯ АДМИН-ПАНЕЛЬ ДЛЯ @hatebeinsober21
# ==========================================
@app.post("/api/admin/execute")
def admin_execute_action(data: ReqAdminAction):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE tg_user_id = ?", (data.admin_id,))
    adm_row = cur.fetchone()
    db_adm_uname = adm_row[0] if adm_row else ""

    if not is_user_admin(data.admin_id, data.admin_username or db_adm_uname):
        conn.close(); raise HTTPException(403, "Доступ закрыт: только для главного разработчика @hatebeinsober21!")

    # Поиск цели по ID или @username (если пусто — выдает самому себе)
    q = (data.target_query or "").strip().replace("@", "")
    target_uid = data.admin_id
    if q:
        if q.isdigit():
            target_uid = int(q)
        else:
            cur.execute("SELECT tg_user_id FROM users WHERE LOWER(username) = LOWER(?)", (q,))
            found = cur.fetchone()
            if not found:
                conn.close(); raise HTTPException(404, f"Игрок @{q} не найден в БД!")
            target_uid = found[0]

    now = int(time.time())
    msg = ""
    if data.action == "give_gram":
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_user_id = ?", (data.amount, target_uid))
        msg = f"✅ Начислено +{int(data.amount):,} GRAM игроку ID {target_uid}!"
    elif data.action == "give_stars":
        cur.execute("UPDATE users SET stars_balance = COALESCE(stars_balance,0) + ? WHERE tg_user_id = ?", (int(data.amount), target_uid))
        msg = f"⭐️ Начислено +{int(data.amount)} Stars на баланс игроку ID {target_uid}!"
    elif data.action == "give_vip":
        cur.execute("UPDATE users SET vip_until = ? WHERE tg_user_id = ?", (now + int(data.amount * 86400), target_uid))
        msg = f"👑 Выдан VIP на {int(data.amount)} дн. игроку ID {target_uid}!"
    elif data.action == "give_luck":
        mult = max(2.0, float(data.amount or 5.0))
        cur.execute("UPDATE users SET luck_multi = ?, luck_until = ? WHERE tg_user_id = ?", (mult, now + 86400, target_uid))
        msg = f"🍀 Выдана Удача ×{mult} на 24ч игроку ID {target_uid}!"
    elif data.action == "give_pass_xp":
        cur.execute("UPDATE users SET season_xp = season_xp + ? WHERE tg_user_id = ?", (int(data.amount), target_uid))
        msg = f"🎫 Начислено +{int(data.amount)} XP Сезонного Пасса!"
    elif data.action == "spawn_item":
        # extra формата "Divine:@durov" или "Exclusive:+888 8 888"
        rar_name = data.extra.split(":")[0] if ":" in data.extra else "Divine"
        custom_tag = data.extra.split(":")[1].strip() if ":" in data.extra else "@durov"
        r_idx = next((i for i, r in enumerate(RARITIES) if r["name"].lower() == rar_name.lower()), 9)
        itype = "number" if custom_tag.startswith("+888") else ("gift" if "#" in custom_tag else "username")
        cand = fast_build_item_in_memory(itype, r_idx, 5.0, quality_override=100, force_blackout=True)
        if custom_tag:
            cand["tag"] = custom_tag
        cur.execute("""
            INSERT OR REPLACE INTO usernames (tag, item_type, owner_id, rarity, quality_pct, income_per_sec, sell_price, num_multi, reasons, is_equipped, channel_slot, is_saved, on_market, is_verified, created_at)
            VALUES (?, ?, ?, ?, 100, ?, ?, ?, ?, 0, 0, 1, 0, 1, ?)
        """, (cand["tag"], itype, target_uid, RARITIES[r_idx]["name"], cand["inc"] * 1.5, max(cand["sell"], float(data.amount or cand["sell"])), cand["num_multi"], cand["reasons"], now))
        msg = f"💎 Предмет {cand['tag']} ({RARITIES[r_idx]['name']}, 100% Идеал + Верификация) выдан в Сейф ID {target_uid}!"
    else:
        conn.close(); raise HTTPException(400, "Неизвестная команда админки")

    conn.commit(); conn.close()
    return {"status": "ok", "message": msg}
