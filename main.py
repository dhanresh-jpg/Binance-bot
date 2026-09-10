import threading
import time
from flask import Flask
import requests

# Clean Configuration Setup
VIP_BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"
FREE_BOT_TOKEN = "8842407289:AAEBSOVQz1NRFmdZFFYsd7TPhoA5TKSJMfk"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)

@app.route('/')
def home():
    return "Automated Signal System is Live!"

def send_telegram_msg(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def fetch_market_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # Primary API: CoinCap (Cloud Hosting Friendly)
    try:
        url = "https://api.coincap.io/v2/assets?limit=10"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json().get('data', [])
            coins = []
            for c in data:
                coins.append({
                    "symbol": c["symbol"].upper() + "USDT",
                    "price": float(c["priceUsd"]),
                    "volume": float(c["volumeUsd24Hr"]),
                    "change": float(c["changePercent24Hr"])
                })
            if coins:
                return coins
    except Exception:
        pass

    # Backup API: CryptoCompare
    try:
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=10&tsym=USD"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json().get("Data", [])
            coins = []
            for item in data:
                raw = item.get("RAW", {}).get("USD", {})
                if raw:
                    coins.append({
                        "symbol": raw.get("FROMSYMBOL", "") + "USDT",
                        "price": float(raw.get("PRICE", 0)),
                        "volume": float(raw.get("VOLUME24HOURTO", 0)),
                        "change": float(raw.get("CHANGEPCT24HOUR", 0))
                    })
            if coins:
                return coins
    except Exception:
        pass

    return []

def signal_engine():
    # 1. Startup Diagnostics
    vip_status = send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, "🟢 *VIP Engine Online*")
    free_status = send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, "🟢 *Free Channel Engine Online*")

    # Audit log if Free channel fails
    if not free_status.get("ok"):
        error_msg = free_status.get("description", "Unknown Telegram Error")
        send_telegram_msg(
            VIP_BOT_TOKEN, 
            VIP_CHANNEL_ID, 
            f"❌ *Free Channel Post Error*:\n`{error_msg}`\n\n*Action Needed*: Free bot ko Free channel ka Admin banayein aur 'Post Messages' ON karein."
        )

    # 2. Fetch Data
    coins = fetch_market_data()
    if not coins:
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, "⚠️ *API Error*: Unable to fetch market data.")
        return

    # 3. Process Signals
    for index, coin in enumerate(coins):
        symbol = coin["symbol"]
        price = coin["price"]
        volume = coin["volume"] / 1_000_000
        change = coin["change"]

        spot_text = (
            f"🟢 *[SPOT SIGNAL] {symbol}*\n\n"
            f"📥 *Entry Range*: ${price:.4f}\n"
            f"📊 *24h Vol*: ${volume:.2f}M | *Change*: {change:+.2f}%\n\n"
            f"🎯 *Target 1*: ${round(price * 1.02, 4)} (+2.0%)\n"
            f"🎯 *Target 2*: ${round(price * 1.045, 4)} (+4.5%)\n"
            f"🎯 *Target 3*: ${round(price * 1.08, 4)} (+8.0%)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.965, 4)} (-3.5%)\n\n"
            f"📈 *Analysis*: Top Volume Momentum"
        )

        futures_text = (
            f"⚡ *[FUTURES LONG] {symbol}*\n\n"
            f"⚙️ *Leverage*: Cross 10x - 20x\n"
            f"📥 *Entry*: ${price:.4f}\n\n"
            f"🎯 *Target 1*: ${round(price * 1.015, 4)} (+15% @ 10x)\n"
            f"🎯 *Target 2*: ${round(price * 1.03, 4)} (+30% @ 10x)\n"
            f"🎯 *Target 3*: ${round(price * 1.05, 4)} (+50% @ 10x)\n"
            f"⛔ *Stop Loss*: ${round(price * 0.985, 4)} (-15% @ 10x)\n\n"
            f"📊 *Analysis*: High Volume Breakout Pattern"
        )

        # Send all 10 signals to VIP Channel
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, spot_text)
        time.sleep(1)
        send_telegram_msg(VIP_BOT_TOKEN, VIP_CHANNEL_ID, futures_text)
        time.sleep(1.5)

        # Send first 2 preview signals to Free Channel
        if index < 2:
            free_promo_text = (
                f"🚀 *FREE PREVIEW SIGNAL* 🚀\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{spot_text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔥 *UNLOCK ALL 10 SPOT & FUTURES SIGNALS* 🔥\n\n"
                f"💳 *Subscription Plans*:\n"
                f"• 10 Days: $10 USDT\n"
                f"• 20 Days: $19 USDT\n"
                f"• 30 Days: $27 USDT\n\n"
                f"👉 *Join VIP Bot*: @BinanceTop10_VIPBot"
            )
            send_telegram_msg(FREE_BOT_TOKEN, FREE_CHANNEL_ID, free_promo_text)
            time.sleep(1.5)

def execution_loop():
    time.sleep(5)
    while True:
        signal_engine()
        time.sleep(3600)

threading.Thread(target=execution_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
