import threading
import time
from flask import Flask
import requests

BOT_TOKEN = "8997353064:AAGqtm4nFQihOzwgIUuWWXRHagTAt8Itq4w"

VIP_CHANNEL_ID = "-1003836756507"
FREE_CHANNEL_ID = "-1003924921868"

app = Flask(__name__)

@app.route('/')
def home():
    return "Automated Signal System Active!"

def send_telegram_msg(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        url = "https://min-api.cryptocompare.com/data/pricemulti?fsyms=BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,DOT&tsyms=USD"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            result = []
            for coin, info in data.items():
                if "USD" in info:
                    result.append({
                        "symbol": coin + "USDT",
                        "price": float(info["USD"]),
                        "volume": 250.0,
                        "change": 2.5
                    })
            if len(result) > 0:
                return result
    except Exception:
        pass
    return []

def signal_engine():
    # Diagnostic test for Free Channel delivery permission
    test_free = send_telegram_msg(FREE_CHANNEL_ID, "🧪 *Free Channel System Test Connection...*")
    
    if not test_free.get("ok"):
        error_details = test_free.get("description", "Unknown Error")
        send_telegram_msg(VIP_CHANNEL_ID, f"❌ *FREE CHANNEL TELEGRAM REJECTION*:\n`{error_details}`")
        return

    coins = fetch_market_data()
    if not coins:
        send_telegram_msg(VIP_CHANNEL_ID, "⚠️ *API Re-connecting...*")
        return

    for index, coin in enumerate(coins):
        symbol = coin["symbol"]
        price = coin["price"]
        volume = coin["volume"]
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

        # VIP Channel Delivery
        send_telegram_msg(VIP_CHANNEL_ID, spot_text)
        time.sleep(1)
        send_telegram_msg(VIP_CHANNEL_ID, futures_text)
        time.sleep(1.5)

        # Free Channel Delivery
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
            send_telegram_msg(FREE_CHANNEL_ID, free_promo_text)
            time.sleep(1.5)

def execution_loop():
    time.sleep(3)
    while True:
        signal_engine()
        time.sleep(3600)

threading.Thread(target=execution_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
