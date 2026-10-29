from datetime import datetime, timedelta, timezone
import os
import random
import sqlite3
import threading
import time
import asyncio
import logging
import re
import html

from flask import Flask, jsonify, request
import requests
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, 
    UserBannedInChannelError, 
    ChatWriteForbiddenError, 
    ChannelPrivateError
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

# ============================================================
# BINANCE TOP 10 - ULTIMATE COMBINED MAIN.PY
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

FREE_BOT_TOKEN = os.getenv(
    "FREE_BOT_TOKEN", "8842407289:AAHD6UcvOZ0pgvN8EJXXetb2qrW-fGeZCvU"
)
VIP_BOT_TOKEN = os.getenv(
    "VIP_BOT_TOKEN", "8997353064:AAH2gTVchfQqqId1TvBa2CD8nIXY00ZUj_8"
)

FREE_CHANNEL_ID = os.getenv("FREE_CHANNEL_ID", "-1003924921868")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "-1003836756507")

TRUST_WALLET_ADDRESS = os.getenv(
    "TRUST_WALLET_ADDRESS",
    "TErttGLUQZtrCwusaQsjdywXdkxUrNFm52"
)

BINANCE_REF_LINK = os.getenv(
    "BINANCE_REF_LINK",
    "https://accounts.binance.com/register?ref=GRO_28502_IBUUM"
)

VIP_BOT_USERNAME = os.getenv("VIP_BOT_USERNAME", "BinanceTop10_VIPBot")
FREE_CHANNEL_USERNAME = os.getenv("FREE_CHANNEL_USERNAME", "BinanceTop10Free")

API_ID = int(os.getenv("TELEGRAM_API_ID", "12345678"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

DB_PATH = os.getenv("DB_PATH", "vip_members.db")

IST = timezone(timedelta(hours=5, minutes=30))
app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BinanceTop10/2.0)"
}

system_logs = []
log_lock = threading.Lock()

free_signals_today = 0
vip_signals_today = 0
last_reset_date = datetime.now(IST).date()
last_free_dispatch_time = 0
last_vip_dispatch_time = 0

FREE_MAX_PER_DAY = 6
VIP_MAX_PER_DAY = 18
FREE_INTERVAL = 4 * 3600
VIP_INTERVAL = 40 * 60

# Signal quality requirements
MIN_VOLUME_USDT = 1_000_000
CANDLE_INTERVAL = "15m"
CANDLE_LIMIT = 100

SENT_PROMO_TRACKER = {}

KEYBOARD_LAYOUT = {
    "keyboard": [
        [
            {"text": "💎 View VIP Plans"},
            {"text": "⚡ Get 1 Signal for $1"}
        ],
        [
            {"text": "💳 Get Payment Address"},
            {"text": "🎁 Free VIP via Referral"}
        ],
        [
            {"text": "🔍 Verify Payment"},
            {"text": "✅ How to Verify TXID"}
        ]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}


# ============================================================
# LOGGING / DB
# ============================================================

def log_event(message):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    with log_lock:
        system_logs.append(entry)
        if len(system_logs) > 300:
            del system_logs[:-300]
    print(entry)


def db_connect():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            expiry_date TEXT,
            status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_txids (
            txid TEXT PRIMARY KEY
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referral_claims (
            user_id INTEGER,
            binance_uid TEXT PRIMARY KEY,
            status TEXT DEFAULT 'PENDING',
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT DEFAULT 'LONG',
            entry_price REAL,
            tp1 REAL,
            tp2 REAL,
            tp3 REAL,
            sl REAL,
            timestamp REAL,
            created_date TEXT,
            status TEXT DEFAULT 'PENDING',
            current_stage INTEGER DEFAULT 0,
            closed INTEGER DEFAULT 0,
            closed_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_seen TEXT,
            last_seen TEXT,
            start_source TEXT DEFAULT 'direct',
            free_join_verified INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_user_id INTEGER UNIQUE,
            source_code TEXT,
            joined_free INTEGER DEFAULT 0,
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invite_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_code TEXT UNIQUE,
            invite_link TEXT,
            created_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT DEFAULT 'IDLE',
            updated_date TEXT
        )
    """)

    existing = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(signal_history)")
    }

    migrations = [
        ("side", "TEXT DEFAULT 'LONG'"),
        ("current_stage", "INTEGER DEFAULT 0"),
        ("closed", "INTEGER DEFAULT 0"),
        ("closed_date", "TEXT"),
    ]

    for col, definition in migrations:
        if col not in existing:
            cur.execute(
                f"ALTER TABLE signal_history ADD COLUMN {col} {definition}"
            )

    conn.commit()
    conn.close()
    log_event("Database initialized / migrated successfully.")


init_db()


def cleanup_old_data():
    try:
        cutoff = (
            datetime.now(IST) - timedelta(days=7)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM signal_history WHERE created_date < ? AND closed = 1",
            (cutoff,)
        )
        cur.execute(
            "DELETE FROM invite_links WHERE created_date < ?",
            (cutoff,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log_event(f"Cleanup error: {e}")


def format_price(value):
    if value is None or value == 0:
        return "0.00"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.001:
        return f"{value:.6f}"
    return f"{value:.8f}"


# ============================================================
# TELEGRAM API
# ============================================================

def tg_request(token, method, payload=None, timeout=15):
    if not token:
        log_event(f"Telegram token missing for {method}")
        return {"ok": False, "description": "Bot token missing"}

    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        res = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )
        return res.json()
    except Exception as e:
        log_event(f"Telegram API {method} error: {e}")
        return {"ok": False, "description": str(e)}


def send_telegram_msg(bot_token, chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    chat_str = str(chat_id)
    if not chat_str.startswith("-"):
        payload["reply_markup"] = reply_markup if reply_markup else KEYBOARD_LAYOUT
    elif reply_markup is not None:
        payload["reply_markup"] = reply_markup

    data = tg_request(bot_token, "sendMessage", payload)

    if not data.get("ok"):
        log_event(
            f"Telegram send failed to {chat_id}: "
            f"{data.get('description')}"
        )
        return False

    return True


def get_chat_member(chat_id, user_id):
    data = tg_request(
        FREE_BOT_TOKEN,
        "getChatMember",
        {"chat_id": chat_id, "user_id": user_id}
    )
    if not data.get("ok"):
        return None
    return data.get("result")


def is_free_channel_member(user_id):
    member = get_chat_member(FREE_CHANNEL_ID, user_id)
    if not member:
        return False

    status = member.get("status")
    return status in ("creator", "administrator", "member")


def create_invite_link(source_code):
    conn = db_connect()
    row = conn.execute(
        "SELECT invite_link FROM invite_links WHERE source_code = ?",
        (source_code,)
    ).fetchone()
    conn.close()

    if row and row["invite_link"]:
        return row["invite_link"]

    data = tg_request(
        FREE_BOT_TOKEN,
        "createChatInviteLink",
        {
            "chat_id": FREE_CHANNEL_ID,
            "name": source_code[:32],
            "creates_join_request": False
        }
    )

    if not data.get("ok"):
        log_event(
            f"Invite creation failed for {source_code}: "
            f"{data.get('description')}"
        )
        return f"https://t.me/{FREE_CHANNEL_USERNAME}"

    invite = data["result"].get("invite_link")

    if invite:
        conn = db_connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO invite_links
            (source_code, invite_link, created_date)
            VALUES (?, ?, ?)
            """,
            (
                source_code,
                invite,
                datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        conn.close()

    return invite


def free_channel_link():
    return f"https://t.me/{FREE_CHANNEL_USERNAME}"


def vip_bot_link(payload=None):
    if payload:
        return f"https://t.me/{VIP_BOT_USERNAME}?start={payload}"
    return f"https://t.me/{VIP_BOT_USERNAME}"


# ============================================================
# USER / REFERRAL TRACKING
# ============================================================

def make_referral_code(user_id):
    return f"ref_{user_id}"


def register_user(user_id, start_source="direct"):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()
    existing = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE users SET last_seen = ? WHERE user_id = ?",
            (now, user_id)
        )
    else:
        code = make_referral_code(user_id)
        conn.execute(
            """
            INSERT INTO users
            (user_id, first_seen, last_seen, start_source, referral_code)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, now, now, start_source, code)
        )

    conn.commit()
    conn.close()


def register_referral(referred_user_id, payload):
    if not payload:
        return

    if not payload.startswith("ref_"):
        return

    raw = payload[4:]
    if not raw.isdigit():
        return

    referrer_id = int(raw)

    if referrer_id == referred_user_id:
        return

    conn = db_connect()

    already = conn.execute(
        "SELECT referred_user_id FROM referrals WHERE referred_user_id = ?",
        (referred_user_id,)
    ).fetchone()

    if already:
        conn.close()
        return

    referrer_exists = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (referrer_id,)
    ).fetchone()

    if not referrer_exists:
        conn.close()
        return

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO referrals
        (referrer_id, referred_user_id, source_code, joined_free, created_date)
        VALUES (?, ?, ?, 0, ?)
        """,
        (referrer_id, referred_user_id, payload, now)
    )

    conn.execute(
        "UPDATE users SET referred_by = ? WHERE user_id = ?",
        (referrer_id, referred_user_id)
    )

    conn.commit()
    conn.close()

    log_event(
        f"Referral registered: {referrer_id} -> {referred_user_id}"
    )


def update_free_join_status(user_id):
    joined = is_free_channel_member(user_id)

    conn = db_connect()
    conn.execute(
        "UPDATE users SET free_join_verified = ? WHERE user_id = ?",
        (1 if joined else 0, user_id)
    )

    if joined:
        conn.execute(
            """
            UPDATE referrals
            SET joined_free = 1
            WHERE referred_user_id = ?
            """,
            (user_id,)
        )

    conn.commit()
    conn.close()

    return joined


# ============================================================
# MARKET DATA & TECHNICAL INDICATORS (RSI / EMA)
# ============================================================

def get_binance_24h():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    res = requests.get(url, headers=HEADERS, timeout=8)
    if res.status_code != 200:
        raise RuntimeError(f"Binance HTTP {res.status_code}")

    data = res.json()
    coins = []

    for item in data:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
            continue

        try:
            price = float(item.get("lastPrice", 0))
            change = float(item.get("priceChangePercent", 0))
            volume = float(item.get("quoteVolume", 0))
            high = float(item.get("highPrice", 0))
            low = float(item.get("lowPrice", 0))
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        coins.append({
            "symbol": symbol,
            "price": price,
            "change": change,
            "volume": volume,
            "high": high,
            "low": low
        })

    return coins


def get_market_data():
    try:
        coins = get_binance_24h()
        if coins:
            return coins
    except Exception as e:
        log_event(f"Binance market data error: {e}")

    try:
        url = "https://api.binance.us/api/v3/ticker/24hr"
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            data = res.json()
            coins = []

            for item in data:
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue

                try:
                    price = float(item.get("lastPrice", 0))
                    change = float(item.get("priceChangePercent", 0))
                    volume = float(item.get("quoteVolume", 0))
                    high = float(item.get("highPrice", 0))
                    low = float(item.get("lowPrice", 0))
                except (TypeError, ValueError):
                    continue

                if price > 0:
                    coins.append({
                        "symbol": symbol,
                        "price": price,
                        "change": change,
                        "volume": volume,
                        "high": high,
                        "low": low
                    })

            if coins:
                log_event("Using Binance.US market-data fallback.")
                return coins

    except Exception as e:
        log_event(f"Binance.US market data error: {e}")

    log_event("No market data available.")
    return []


def get_klines(symbol, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT):
    url = "https://api.binance.com/api/v3/klines"
    res = requests.get(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        headers=HEADERS,
        timeout=8
    )

    if res.status_code != 200:
        raise RuntimeError(
            f"Klines HTTP {res.status_code}: {res.text[:100]}"
        )

    return res.json()


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema

    return ema


def get_technical_data(symbol):
    try:
        candles = get_klines(symbol)

        if len(candles) < 50:
            return None

        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        volumes = [float(c[5]) for c in candles]

        rsi = calculate_rsi(closes, 14)
        ema20 = calculate_ema(closes[-50:], 20)
        ema50 = calculate_ema(closes[-50:], 50)

        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])

        avg_volume = sum(volumes[-20:]) / 20
        current_volume = volumes[-1]

        return {
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "support": recent_low,
            "resistance": recent_high,
            "volume": current_volume,
            "avg_volume": avg_volume,
            "current": closes[-1]
        }

    except Exception as e:
        log_event(f"Technical data error {symbol}: {e}")
        return None


# ============================================================
# SIGNAL ENGINE
# ============================================================

def build_signal(candidate):
    symbol = candidate["symbol"]
    price = candidate["price"]
    change = candidate["change"]
    volume = candidate["volume"]

    if volume < MIN_VOLUME_USDT:
        return None

    tech = get_technical_data(symbol)
    if not tech:
        return None

    rsi = tech["rsi"]
    ema20 = tech["ema20"]
    ema50 = tech["ema50"]

    if rsi is None or ema20 is None or ema50 is None:
        return None

    if rsi >= 78 or rsi <= 22:
        return None

    long_score = 0
    short_score = 0

    if ema20 > ema50:
        long_score += 2
    elif ema20 < ema50:
        short_score += 2

    if change > 0.8:
        long_score += 1
    elif change < -0.8:
        short_score += 1

    if rsi >= 50:
        long_score += 1
    elif rsi <= 50:
        short_score += 1

    if tech["volume"] >= tech["avg_volume"] * 1.15:
        if change > 0:
            long_score += 1
        elif change < 0:
            short_score += 1

    if long_score >= 4 and long_score > short_score:
        side = "LONG"
    elif short_score >= 4 and short_score > long_score:
        side = "SHORT"
    else:
        return None

    if side == "LONG":
        tp1 = price * 1.006
        tp2 = price * 1.012
        tp3 = price * 1.020
        sl = price * 0.990
        mode = "15M FUTURES SCALP LONG"
    else:
        tp1 = price * 0.994
        tp2 = price * 0.988
        tp3 = price * 0.980
        sl = price * 1.010
        mode = "15M FUTURES SCALP SHORT"

    return {
        "symbol": symbol,
        "price": price,
        "side": side,
        "mode": mode,
        "leverage": "Cross 10x - 20x",
        "rsi": round(rsi, 2),
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl": sl,
        "change": round(change, 2),
        "support": tech["support"],
        "resistance": tech["resistance"],
        "volume_ratio": round(
            tech["volume"] / tech["avg_volume"], 2
        ) if tech["avg_volume"] else 0,
        "score": max(long_score, short_score)
    }


def find_best_signal():
    coins = get_market_data()
    if not coins:
        return None

    candidates = [
        c for c in coins
        if c["volume"] >= MIN_VOLUME_USDT
        and abs(c["change"]) >= 0.8
    ]

    candidates.sort(
        key=lambda x: (
            abs(x["change"]),
            x["volume"]
        ),
        reverse=True
    )

    for candidate in candidates[:15]:
        signal = build_signal(candidate)
        if signal:
            return signal

    return None


# ============================================================
# USERBOT MARKETING ENGINE
# ============================================================

client_userbot = TelegramClient("growth_userbot_session", API_ID, API_HASH)

def get_dynamic_promo_post():
    headers = [
        "🔥 <b>ACCURATE CRYPTO SIGNALS</b> 🔥",
        "⚡ <b>BINANCE FUTURES SIGNAL VIP</b> ⚡",
        "🚀 <b>HIGH-ACCURACY TRADING SIGNALS</b> 🚀"
    ]
    bodies = [
        "Daily High-Accuracy Signals & Live Market Analysis.\nJoin our channel now and start making profits daily!",
        "Don't trade blindly in this market! Real-time TP/SL alerts and expert technical analysis provided."
    ]
    ctas = [
        f"👉 <b>Join Free Channel:</b> @{FREE_CHANNEL_USERNAME}\n💎 <b>Bot Link:</b> @{VIP_BOT_USERNAME}"
    ]
    return f"{random.choice(headers)}\n\n{random.choice(bodies)}\n\n{random.choice(ctas)}"


async def safe_send_userbot_message(chat_username, text, reply_to=None):
    try:
        msg = await client_userbot.send_message(chat_username, text, parse_mode='html', reply_to=reply_to)
        return msg
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 5)
        return None
    except Exception:
        return None


async def broadcast_signal_hit_to_marketing_groups(pair_name, target_name):
    hit_text = (
        f"🎯 <b>SIGNAL HIT UPDATE: #{pair_name}</b> 🎯\n\n"
        f"✅ <b>Status:</b> {target_name}\n\n"
        f"💰 Join VIP Channel: @{FREE_CHANNEL_USERNAME}\n"
        f"🤖 Direct VIP Access: @{VIP_BOT_USERNAME}"
    )
    groups_to_remove = []
    for group_username, last_msg_id in list(SENT_PROMO_TRACKER.items()):
        sent_msg = await safe_send_userbot_message(group_username, hit_text, reply_to=last_msg_id)
        if sent_msg is None:
            groups_to_remove.append(group_username)
        await asyncio.sleep(random.randint(10, 20))

    for g in groups_to_remove:
        SENT_PROMO_TRACKER.pop(g, None)


async def auto_discover_and_market():
    if not API_ID or not API_HASH or API_ID == 12345678:
        log_event("⚠️ Userbot skipped: TELEGRAM_API_ID or TELEGRAM_API_HASH not configured.")
        return
    try:
        await client_userbot.start()
        log_event("🚀 Userbot Marketing Engine Started!")
    except Exception as e:
        log_event(f"❌ Userbot Start Failed: {e}")
        return

    keywords = ["binance trading india", "crypto signals free", "bitcoin trading group", "crypto scalping"]
    nsfw_blacklist = ["chatting", "friend", "fun", "dating", "adult", "sexy", "nsfw", "desi", "call", "girl"]

    while True:
        try:
            if not client_userbot.is_connected():
                await client_userbot.connect()
            keyword = random.choice(keywords)
            result = await client_userbot(SearchRequest(q=keyword, limit=5))
            for chat in result.chats:
                if (isinstance(chat, Chat) or (isinstance(chat, Channel) and getattr(chat, "megagroup", False))) and getattr(chat, "username", None):
                    uname = chat.username.lower()
                    title = getattr(chat, "title", "").lower()
                    if any(bad in title or bad in uname for bad in nsfw_blacklist):
                        continue
                    try:
                        await client_userbot(JoinChannelRequest(uname))
                        await asyncio.sleep(10)
                        sent_msg = await safe_send_userbot_message(uname, get_dynamic_promo_post())
                        if sent_msg:
                            SENT_PROMO_TRACKER[uname] = sent_msg.id
                        await asyncio.sleep(60)
                    except Exception:
                        pass
        except Exception as e:
            log_event(f"Userbot Loop Error: {e}")
        await asyncio.sleep(1800)


def start_marketing_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(auto_discover_and_market())
    except Exception as e:
        log_event(f"Marketing Thread Error: {e}")


# ============================================================
# SIGNAL MESSAGES & DISPATCH
# ============================================================

def signal_message(s, vip=False):
    if vip:
        return (
            "🚨 <b>BINANCE VIP TRADE SIGNAL</b> 🚨\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 <b>Pair:</b> #{html.escape(s['symbol'])}\n"
            f"📊 <b>Side:</b> {s['side']}\n"
            f"📈 <b>Setup:</b> {s['mode']}\n"
            f"⚙️ <b>Leverage:</b> {s['leverage']}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>Entry:</b> ${format_price(s['price'])}\n"
            f"🎯 <b>TP1:</b> ${format_price(s['tp1'])}\n"
            f"🎯 <b>TP2:</b> ${format_price(s['tp2'])}\n"
            f"🚀 <b>TP3:</b> ${format_price(s['tp3'])}\n"
            f"⛔ <b>SL:</b> ${format_price(s['sl'])}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>RSI:</b> {s['rsi']}\n"
            f"🛡️ <b>Support:</b> ${format_price(s['support'])}\n"
            f"🚧 <b>Resistance:</b> ${format_price(s['resistance'])}\n"
            f"📈 <b>24h Change:</b> {s['change']}%\n"
            f"📊 <b>Signal Score:</b> {s['score']}/5\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Binance:</b> {BINANCE_REF_LINK}\n"
            "⚠️ <i>Use strict risk management.</i>"
        )

    return (
        "🔥 <b>FREE SIGNAL PREVIEW</b> 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b> #{html.escape(s['symbol'])}\n"
        f"📊 <b>Side:</b> {s['side']}\n"
        f"📥 <b>Entry:</b> ${format_price(s['price'])}\n"
        f"🎯 <b>TP1:</b> ${format_price(s['tp1'])}\n"
        f"⛔ <b>SL:</b> <tg-spoiler>🔒 VIP ONLY</tg-spoiler>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>RSI:</b> {s['rsi']}\n"
        f"💎 <b>Full TP1/TP2/TP3 + live updates:</b> {vip_bot_link()}\n\n"
        "⚠️ <i>Market analysis only.</i>"
    )


def save_signal(s):
    conn = db_connect()
    now = time.time()
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.execute(
        """
        INSERT INTO signal_history
        (symbol, side, entry_price, tp1, tp2, tp3, sl,
         timestamp, created_date, status, current_stage, closed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, 0)
        """,
        (
            s["symbol"], s["side"], s["price"], s["tp1"], s["tp2"], s["tp3"], s["sl"], now, now_str
        )
    )
    signal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def dispatch_vip_signal(s):
    return send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, signal_message(s, vip=True))


def dispatch_free_signal(s):
    return send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, signal_message(s, vip=False))


def reset_daily_counters_if_needed():
    global free_signals_today, vip_signals_today, last_reset_date
    today = datetime.now(IST).date()
    if today != last_reset_date:
        free_signals_today = 0
        vip_signals_today = 0
        last_reset_date = today
        cleanup_old_data()


def scan_and_dispatch(force_mode=False):
    global free_signals_today, vip_signals_today, last_free_dispatch_time, last_vip_dispatch_time
    reset_daily_counters_if_needed()

    now = time.time()
    signal = find_best_signal()
    if not signal:
        log_event("No high-quality signal found in this scan.")
        return False

    vip_allowed = force_mode or (vip_signals_today < VIP_MAX_PER_DAY and now - last_vip_dispatch_time >= VIP_INTERVAL)
    free_allowed = force_mode or (free_signals_today < FREE_MAX_PER_DAY and now - last_free_dispatch_time >= FREE_INTERVAL)

    sent_any = False
    if vip_allowed:
        if dispatch_vip_signal(signal):
            vip_signals_today += 1
            last_vip_dispatch_time = now
            sent_any = True

    if free_allowed:
        if dispatch_free_signal(signal):
            free_signals_today += 1
            last_free_dispatch_time = now
            sent_any = True

    if sent_any:
        save_signal(signal)

    return sent_any


# ============================================================
# LIVE TP/SL MONITOR
# ============================================================

def update_signal_stage(signal_id, status, stage, closed=0):
    conn = db_connect()
    if closed:
        conn.execute(
            """
            UPDATE signal_history
            SET status = ?, current_stage = ?, closed = 1, closed_date = ?
            WHERE id = ?
            """,
            (status, stage, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), signal_id)
        )
    else:
        conn.execute(
            """
            UPDATE signal_history
            SET status = ?, current_stage = ?
            WHERE id = ?
            """,
            (status, stage, signal_id)
        )
    conn.commit()
    conn.close()


def send_signal_update(sym, side, entry, current_price, text):
    message = (
        "🔔 <b>LIVE SIGNAL UPDATE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b> #{sym}\n"
        f"📊 <b>Side:</b> {side}\n"
        f"📥 <b>Entry:</b> ${format_price(entry)}\n"
        f"📊 <b>Current:</b> ${format_price(current_price)}\n"
        f"🔥 <b>Status:</b> {text}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>VIP:</b> {vip_bot_link()}"
    )
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, message)
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, message)


def live_signal_monitor_worker():
    log_event("Live TP/SL monitor started.")
    while True:
        try:
            conn = db_connect()
            rows = conn.execute(
                """
                SELECT id, symbol, side, entry_price, tp1, tp2, tp3, sl, current_stage, status
                FROM signal_history
                WHERE closed = 0
                """
            ).fetchall()
            conn.close()

            if not rows:
                time.sleep(60)
                continue

            coins = get_market_data()
            prices = {c["symbol"]: c["price"] for c in coins}

            for row in rows:
                signal_id = row["id"]
                sym = row["symbol"]
                side = row["side"]
                entry = row["entry_price"]
                tp1, tp2, tp3, sl = row["tp1"], row["tp2"], row["tp3"], row["sl"]
                stage = row["current_stage"]
                status = row["status"]

                current = prices.get(sym)
                if not current:
                    continue

                new_stage = stage
                event = None
                closed = False

                if side == "LONG":
                    if current >= tp3 and stage < 3:
                        new_stage, event, status, closed = 3, f"🚀 TP3 HIT @ ${format_price(tp3)}", "TP3_HIT", True
                    elif current >= tp2 and stage < 2:
                        new_stage, event, status = 2, f"🎯 TP2 HIT @ ${format_price(tp2)}", "TP2_HIT"
                    elif current >= tp1 and stage < 1:
                        new_stage, event, status = 1, f"✅ TP1 HIT @ ${format_price(tp1)}", "TP1_HIT"
                    elif current <= sl:
                        status = "STOP_AFTER_TARGET" if stage > 0 else "SL_HIT"
                        event = f"⛔ Stop reached after TP{stage} @ ${format_price(sl)}" if stage > 0 else f"⛔ SL HIT @ ${format_price(sl)}"
                        closed = True
                else:
                    if current <= tp3 and stage < 3:
                        new_stage, event, status, closed = 3, f"🚀 TP3 HIT @ ${format_price(tp3)}", "TP3_HIT", True
                    elif current <= tp2 and stage < 2:
                        new_stage, event, status = 2, f"🎯 TP2 HIT @ ${format_price(tp2)}", "TP2_HIT"
                    elif current <= tp1 and stage < 1:
                        new_stage, event, status = 1, f"✅ TP1 HIT @ ${format_price(tp1)}", "TP1_HIT"
                    elif current >= sl:
                        status = "STOP_AFTER_TARGET" if stage > 0 else "SL_HIT"
                        event = f"⛔ Stop reached after TP{stage} @ ${format_price(sl)}" if stage > 0 else f"⛔ SL HIT @ ${format_price(sl)}"
                        closed = True

                if event:
                    update_signal_stage(signal_id, status, new_stage, 1 if closed else 0)
                    send_signal_update(sym, side, entry, current, event)
                    try:
                        asyncio.run(broadcast_signal_hit_to_marketing_groups(sym, event))
                    except Exception:
                        pass
        except Exception as e:
            log_event(f"Live monitor error: {e}")
        time.sleep(60)


# ============================================================
# RESULT STATISTICS & REPORTS
# ============================================================

def get_result_stats(hours=24):
    cutoff = (datetime.now(IST) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db_connect()
    rows = conn.execute("SELECT status, current_stage, closed FROM signal_history WHERE created_date >= ?", (cutoff,)).fetchall()
    conn.close()

    total = len(rows)
    tp1 = sum(r["current_stage"] >= 1 for r in rows)
    tp2 = sum(r["current_stage"] >= 2 for r in rows)
    tp3 = sum(r["current_stage"] >= 3 for r in rows)
    sl = sum(r["status"] == "SL_HIT" for r in rows)
    stop_after_target = sum(r["status"] == "STOP_AFTER_TARGET" for r in rows)
    closed = sum(r["closed"] == 1 for r in rows)

    clean_wins = tp3
    clean_losses = sl
    decided = clean_wins + clean_losses
    win_rate = round(clean_wins / decided * 100, 1) if decided else 0.0

    return {
        "total": total, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "stop_after_target": stop_after_target, "closed": closed, "win_rate": win_rate
    }


def generate_24h_result_report():
    stats = get_result_stats(24)
    msg = (
        "📊 <b>24-HOUR SIGNAL REPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Total Signals:</b> {stats['total']}\n"
        f"✅ <b>TP1 Reached:</b> {stats['tp1']}\n"
        f"🎯 <b>TP2 Reached:</b> {stats['tp2']}\n"
        f"🚀 <b>TP3 Reached:</b> {stats['tp3']}\n"
        f"⛔ <b>Clean SL:</b> {stats['sl']}\n"
        f"📈 <b>Clean Win Rate:</b> {stats['win_rate']}%\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>VIP:</b> {vip_bot_link()}"
    )
    send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, msg)
    send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, msg)


# ============================================================
# BOT HANDLERS ($1 TRIAL, REFERRAL, & PAYMENT)
# ============================================================

def set_user_state(user_id, state):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO user_states (user_id, state, updated_date) VALUES (?, ?, ?)",
        (user_id, state, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def get_user_state(user_id):
    conn = db_connect()
    row = conn.execute("SELECT state FROM user_states WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row["state"] if row else "IDLE"


def get_referral_stats(user_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(joined_free) AS joined FROM referrals WHERE referrer_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return {"total": int(row["total"] or 0), "joined": int(row["joined"] or 0)}


def get_or_create_user_invite(user_id):
    return vip_bot_link(make_referral_code(user_id))


def generate_instant_trial_signal(chat_id):
    signal = build_signal() or {"symbol": "BTCUSDT", "price": 65000, "side": "LONG", "mode": "FUTURES SCALP", "leverage": "10x", "rsi": 55, "tp1": 65500, "tp2": 66000, "tp3": 67000, "sl": 64000}
    msg = (
        f"⚡ <b>YOUR PAID $1 TRIAL VIP SIGNAL</b> ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>Pair:</b> #{signal['symbol']}\n"
        f"📊 <b>Side:</b> {signal['side']}\n"
        f"📥 <b>Entry:</b> ${format_price(signal['price'])}\n"
        f"🎯 <b>TP1:</b> ${format_price(signal['tp1'])}\n"
        f"🎯 <b>TP2:</b> ${format_price(signal['tp2'])}\n"
        f"🚀 <b>TP3:</b> ${format_price(signal['tp3'])}\n"
        f"⛔ <b>SL:</b> ${format_price(signal['sl'])}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Upgrade to Full VIP:</b> {vip_bot_link()}"
    )
    send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg)


def handle_bot_message(chat_id, text):
    text_clean = text.strip()
    if text_clean.startswith("/start"):
        parts = text_clean.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else "direct"
        register_user(chat_id, payload)
        register_referral(chat_id, payload)
        
        msg = (
            "🤖 <b>Welcome to Binance Top 10 Signals</b>\n\n"
            "⚡ <b>Trial Offer:</b> Get 1 High-Accuracy VIP Signal for <b>$1 USDT</b>!\n"
            f"📢 <b>Free Channel:</b> {free_channel_link()}"
        )
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, msg, KEYBOARD_LAYOUT)
        return

    register_user(chat_id)

    if text_clean == "📢 Join Free Channel":
        invite = create_invite_link(f"user_{chat_id}")
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"👉 <a href=\"{invite}\">JOIN FREE CHANNEL</a>\nThen tap Verify Free Join.")
    elif text_clean == "✅ Verify Free Join":
        joined = update_free_join_status(chat_id)
        if joined:
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "✅ Free Channel membership verified!")
        else:
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "❌ Join not detected yet.")
    elif text_clean == "🎁 My Referral Link":
        link = get_or_create_user_invite(chat_id)
        stats = get_referral_stats(chat_id)
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"🎁 <b>Your Link:</b>\n<code>{link}</code>\nTotal Referrals: {stats['total']}")
    elif text_clean == "📊 24H Results":
        stats = get_result_stats(24)
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"📊 <b>Results:</b> Signals: {stats['total']} | Win Rate: {stats['win_rate']}%")
    elif text_clean == "💎 View VIP Plans":
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, "💎 <b>Plans:</b>\n• $1 Trial Signal\n• 10 Days — $10 USDT\n• 20 Days — $18 USDT\n• 30 Days — $27 USDT")
    elif text_clean in ("💳 Get Payment Address", "🔍 Verify Payment"):
        set_user_state(chat_id, "AWAITING_TXID")
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"💳 <b>USDT TRC20 Address:</b>\n<code>{TRUST_WALLET_ADDRESS}</code>\n\nSend payment and send your TXID here.")
    elif text_clean == "✅ How to Verify TXID":
        send_telegram_msg(VIP_BOT_TOKEN, chat_id, "📖 Send USDT (TRC20) and send your transaction hash (TXID) here.")
    elif text_clean.isdigit() and 7 <= len(text_clean) <= 12:
        # Binance UID handling
        conn = db_connect()
        try:
            conn.execute(
                "INSERT INTO referral_claims (user_id, binance_uid, status, created_date) VALUES (?, ?, 'PENDING', ?)",
                (chat_id, text_clean, datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "📥 <b>Binance UID received!</b> Admin verification pending.")
        except Exception:
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "⚠️ This Binance UID is already submitted.")
        finally:
            conn.close()
    else:
        txid = text_clean
        if not re.fullmatch(r"[A-Za-z0-9]{20,100}", txid):
            return

        conn = db_connect()
        if conn.execute("SELECT txid FROM processed_txids WHERE txid = ?", (txid,)).fetchone():
            conn.close()
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "⚠️ This TXID has already been used.")
            return

        valid, amount, reason = verify_usdt_trc20_tx(txid, 1.0)
        if not valid:
            conn.close()
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"❌ Verification failed: {reason}")
            return

        conn.execute("INSERT INTO processed_txids (txid) VALUES (?)", (txid,))
        
        if 1.0 <= amount < 9.0:
            conn.commit()
            conn.close()
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, "✅ $1 Payment Verified! Dispatching your Trial Signal...")
            generate_instant_trial_signal(chat_id)
        else:
            days = 30 if amount >= 27 else (20 if amount >= 18 else 10)
            plan = "30 Days VIP" if days == 30 else ("20 Days VIP" if days == 20 else "10 Days VIP")
            expiry = (datetime.now(IST) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT OR REPLACE INTO members (user_id, expiry_date, status) VALUES (?, ?, 'ACTIVE')", (chat_id, expiry))
            conn.commit()
            conn.close()
            send_telegram_msg(VIP_BOT_TOKEN, chat_id, f"✅ <b>Payment Verified!</b> {plan} active till {expiry}.")


def verify_usdt_trc20_tx(txid, expected_amount_min=1.0):
    try:
        url = f"https://apilist.tronscan.org/api/transaction-info?hash={txid.strip()}"
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return False, 0, "Blockchain API error."
        data = res.json()
        if not data or data.get("contractRet") not in (None, "SUCCESS"):
            return False, 0, "Transaction failed or unconfirmed."
        
        for transfer in data.get("trc20TransferInfo", []):
            if transfer.get("to_address") == TRUST_WALLET_ADDRESS and transfer.get("symbol", "").upper() == "USDT":
                amt = float(transfer.get("amount_str", "0")) / 10**6
                if amt >= expected_amount_min:
                    return True, amt, "Success"
        return False, 0, "Recipient or amount does not match."
    except Exception as e:
        return False, 0, str(e)


# ============================================================
# EXPIRY & REMINDER WORKERS
# ============================================================

def membership_expiry_checker():
    log_event("Membership expiry worker started.")
    while True:
        try:
            now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            conn = db_connect()
            rows = conn.execute("SELECT user_id FROM members WHERE expiry_date <= ? AND status = 'ACTIVE'", (now,)).fetchall()
            for row in rows:
                u_id = row["user_id"]
                tg_request(VIP_BOT_TOKEN, "banChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": u_id})
                tg_request(VIP_BOT_TOKEN, "unbanChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": u_id, "only_if_banned": True})
                conn.execute("UPDATE members SET status = 'EXPIRED' WHERE user_id = ?", (u_id,))
                send_telegram_msg(VIP_BOT_TOKEN, u_id, "⚠️ <b>Your VIP membership has expired.</b>")
            conn.commit()
            conn.close()
        except Exception as e:
            log_event(f"Expiry worker error: {e}")
        time.sleep(3600)


def telegram_polling_worker():
    log_event("Telegram polling worker started.")
    offset = 0
    try:
        tg_request(VIP_BOT_TOKEN, "deleteWebhook", {"drop_pending_updates": False})
    except Exception:
        pass

    while True:
        try:
            data = tg_request(VIP_BOT_TOKEN, "getUpdates", {"offset": offset, "timeout": 30}, timeout=35)
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if msg and "chat" in msg and "text" in msg:
                        threading.Thread(target=handle_bot_message, args=(msg["chat"]["id"], msg["text"]), daemon=True).start()
        except Exception as e:
            log_event(f"Polling error: {e}")
        time.sleep(2)


def continuous_market_scanner():
    log_event("Market scanner started.")
    while True:
        try:
            scan_and_dispatch(False)
        except Exception as e:
            log_event(f"Scanner error: {e}")
        time.sleep(120)


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return jsonify({"status": "active", "service": "BinanceTop10", "time": datetime.now(IST).isoformat()})


@app.route("/logs")
def get_logs():
    with log_lock:
        return jsonify({"logs": list(system_logs)})


@app.route("/force-signal")
def force_signal():
    threading.Thread(target=scan_and_dispatch, args=(True,), daemon=True).start()
    return jsonify({"status": "success", "message": "Force scan triggered."})


@app.route("/force-result")
def force_result():
    threading.Thread(target=generate_24h_result_report, daemon=True).start()
    return jsonify({"status": "success", "message": "24h result report triggered."})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(IST).isoformat()})


# ============================================================
# START WORKERS
# ============================================================

threading.Thread(target=telegram_polling_worker, daemon=True).start()
threading.Thread(target=continuous_market_scanner, daemon=True).start()
threading.Thread(target=live_signal_monitor_worker, daemon=True).start()
threading.Thread(target=membership_expiry_checker, daemon=True).start()
threading.Thread(target=start_marketing_thread, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
