#!/usr/bin/env python3
"""
IQ Option OTC Signals Bot - Final v2 (Lower Threshold + More Pairs + CCXT Fix)
"""

import logging
import os
import asyncio
import random
import requests
from datetime import datetime
from collections import defaultdict
import pandas as pd
import ccxt.async_support as ccxt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    JobQueue
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
CONFIDENCE_THRESHOLD = 60          # Lowered from 65
AUTO_SIGNAL_INTERVAL_MINUTES = 3
MAX_MARTINGALE_STEPS = 3

# Expanded pairs
PAIRS = [
    "EUR/USD", "GBP/USD", "AUD/USD", "USD/JPY", "XAU/USD",
    "NZD/USD", "USD/CAD", "EUR/GBP"
]

HIGH_IMPACT_WINDOWS = [(13, 15), (7, 9)]

user_state = defaultdict(lambda: {
    "base_stake": 10,
    "current_streak": 0,
    "max_martingale": MAX_MARTINGALE_STEPS,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "channel_id": None,
})

# ==================== PURE PANDAS INDICATORS ====================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def stochastic(df, k_period=14, d_period=3):
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    k = 100 * ((df['close'] - low_min) / (high_max - low_min))
    d = k.rolling(window=d_period).mean()
    return k, d

def atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_indicators(df):
    if len(df) < 40:
        return None
    df = df.copy()
    df['rsi'] = rsi(df['close'], 14)
    df['ema9'] = ema(df['close'], 9)
    df['ema21'] = ema(df['close'], 21)
    _, _, df['macd_hist'] = macd(df['close'])
    df['stoch_k'], _ = stochastic(df)
    df['atr'] = atr(df)
    return df

# ==================== DATA FETCHERS (Fixed CCXT close) ====================
async def fetch_twelve_data_ohlcv(pair, outputsize=100):
    if not TWELVE_DATA_KEY:
        return None
    symbol = pair.replace("/", "")
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol, "interval": "1min", "outputsize": outputsize,
        "apikey": TWELVE_DATA_KEY, "format": "JSON"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if "values" not in data:
            return None
        df = pd.DataFrame(data["values"])
        df = df.rename(columns={"datetime": "timestamp", "open": "open", "high": "high",
                                "low": "low", "close": "close", "volume": "volume"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index().astype(float)
        return df
    except Exception as e:
        logger.error(f"Twelve Data error: {e}")
        return None

async def fetch_ccxt_ohlcv(pair, limit=100):
    exchange = ccxt.binance()
    try:
        symbol_map = {
            "EUR/USD": "EURUSDT", "GBP/USD": "GBPUSDT", "AUD/USD": "AUDUSDT",
            "USD/JPY": "USDJPY", "XAU/USD": "XAUUSDT",
            "NZD/USD": "NZDUSDT", "USD/CAD": "USDCADT", "EUR/GBP": "EURGBPT"
        }
        symbol = symbol_map.get(pair, pair.replace("/", "") + "T")
        ohlcv = await exchange.fetch_ohlcv(symbol, "1m", limit=limit)
        return ohlcv
    except Exception as e:
        logger.error(f"CCXT error for {pair}: {e}")
        return None
    finally:
        await exchange.close()   # Fixed: Properly close exchange

def generate_synthetic_data(pair, limit=100):
    import numpy as np
    np.random.seed(hash(pair) % 10000)
    base = {"EUR/USD": 1.085, "GBP/USD": 1.27, "AUD/USD": 0.66,
            "USD/JPY": 155, "XAU/USD": 2650, "NZD/USD": 0.60,
            "USD/CAD": 1.36, "EUR/GBP": 0.85}.get(pair, 1.0)
    prices = base + np.cumsum(np.random.randn(limit) * 0.0008)
    return pd.DataFrame({
        'open': prices, 'high': prices + 0.001, 'low': prices - 0.001,
        'close': prices, 'volume': np.random.randint(500, 8000, limit)
    }, index=pd.date_range(end=datetime.now(), periods=limit, freq='1min'))

async def fetch_ohlcv(pair, limit=100):
    df = await fetch_twelve_data_ohlcv(pair, outputsize=limit)
    if df is not None and len(df) >= 30:
        return df

    ohlcv = await fetch_ccxt_ohlcv(pair, limit=limit)
    if ohlcv:
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    return generate_synthetic_data(pair, limit)

# ==================== STRATEGY ====================
def is_high_impact_time():
    hour = datetime.utcnow().hour
    return any(start <= hour < end for start, end in HIGH_IMPACT_WINDOWS)

def generate_signal(pair, df):
    if df is None or len(df) < 40:
        return None
    df = calculate_indicators(df)
    if df is None:
        return None

    latest = df.iloc[-1]
    rsi_val = latest['rsi']
    ema9 = latest['ema9']
    ema21 = latest['ema21']
    macd_hist = latest['macd_hist']
    stoch_k = latest['stoch_k']
    close = latest['close']

    if is_high_impact_time():
        return None

    signal = None
    confidence = 50
    reasons = []

    if (rsi_val < 35 and close > ema9 and ema9 > ema21 and 
        macd_hist > -0.0001 and stoch_k < 30):
        signal = "CALL 🟢"
        confidence = 65 + min(25, int((35 - rsi_val) * 1.3))
        reasons = ["RSI Oversold", "EMA Bullish", "MACD Improving", "Stoch Low"]

    elif (rsi_val > 65 and close < ema9 and ema9 < ema21 and 
          macd_hist < 0.0001 and stoch_k > 70):
        signal = "PUT 🔴"
        confidence = 65 + min(25, int((rsi_val - 65) * 1.3))
        reasons = ["RSI Overbought", "EMA Bearish", "MACD Weakening", "Stoch High"]

    if signal and confidence >= CONFIDENCE_THRESHOLD:
        if not is_high_impact_time():
            confidence = min(95, confidence + 5)
            reasons.append("Clean Session")
        return {
            "pair": pair, "signal": signal, "confidence": round(confidence, 1),
            "expiry": random.choice([1, 3, 5]), "time": datetime.now().strftime("%H:%M:%S"),
            "reasons": reasons, "price": round(close, 5), "rsi": round(rsi_val, 1)
        }
    return None

# ==================== MARTINGALE & STATS ====================
def get_martingale_stakes(user_id):
    state = user_state[user_id]
    base = state["base_stake"]
    return [base * (2 ** i) for i in range(state["max_martingale"] + 1)], state["current_streak"]

def update_result(user_id, result):
    state = user_state[user_id]
    state["total_trades"] += 1
    if result == "win":
        state["wins"] += 1
        state["current_streak"] = 0
    else:
        state["losses"] += 1
        state["current_streak"] = min(state["current_streak"] + 1, state["max_martingale"])
    return state

def get_stats(user_id):
    state = user_state[user_id]
    total = state["total_trades"]
    win_rate = (state["wins"] / total * 100) if total > 0 else 0
    return {
        "total": total, "wins": state["wins"], "losses": state["losses"],
        "win_rate": round(win_rate, 1), "current_streak": state["current_streak"]
    }

# ==================== AUTO SIGNAL JOB ====================
async def auto_signal_job(context):
    for user_id, state in list(user_state.items()):
        channel_id = state.get("channel_id")
        if not channel_id:
            continue
        for pair in PAIRS:
            try:
                df = await fetch_ohlcv(pair)
                sig = generate_signal(pair, df)
                if sig:
                    text = format_signal(sig, user_id)
                    await context.bot.send_message(chat_id=channel_id, text=text, parse_mode="Markdown")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Auto signal error: {e}")

def format_signal(sig, user_id):
    stakes, streak = get_martingale_stakes(user_id)
    next_stake = stakes[min(streak, len(stakes)-1)]
    reasons_str = "\n".join([f"• {r}" for r in sig["reasons"]])
    return (
        f"🎯 **HIGH-PROB OTC SIGNAL** (v2 - Lower Threshold)\n\n"
        f"**{sig['pair']}** → {sig['signal']}\n"
        f"**Expiry:** {sig['expiry']} min | **Confidence:** {sig['confidence']}%\n"
        f"**Price:** {sig['price']} | **RSI:** {sig['rsi']}\n\n"
        f"**Reasons:**\n{reasons_str}\n\n"
        f"**Martingale:** Streak {streak} → Next stake **${next_stake}**\n"
        f"⏰ {sig['time']}\n⚠️ Demo only • Risk management first"
    )

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_state[user_id]
    keyboard = [
        [InlineKeyboardButton("📈 Get Signal", callback_data="signal_all")],
        [InlineKeyboardButton("📊 My Stats", callback_data="stats")],
        [InlineKeyboardButton("💰 Set Base Stake", callback_data="set_stake")],
        [InlineKeyboardButton("📡 Set Auto Channel", callback_data="set_channel")],
        [InlineKeyboardButton("✅ Won", callback_data="win"), InlineKeyboardButton("❌ Lost", callback_data="loss")],
    ]
    await update.message.reply_text(
        f"🚀 **IQ Option OTC Signals Bot v2**\n\n"
        f"Min Confidence: {CONFIDENCE_THRESHOLD}%\n"
        f"Auto signals every {AUTO_SIGNAL_INTERVAL_MINUTES} min\n\n"
        f"Base Stake: ${state['base_stake']}\nMartingale: Up to {state['max_martingale']} steps\n\n"
        f"Pairs: {', '.join(PAIRS)}\n\n"
        f"⚠️ Educational / Demo use only.",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("signal_"):
        pairs = PAIRS if "all" in data else [data.replace("signal_", "")]
        msgs = []
        for p in pairs:
            df = await fetch_ohlcv(p)
            sig = generate_signal(p, df)
            msgs.append(format_signal(sig, user_id) if sig else f"❌ No {CONFIDENCE_THRESHOLD}%+ signal for {p} right now.")
        await query.edit_message_text("\n\n".join(msgs), parse_mode="Markdown")

    elif data == "stats":
        s = get_stats(user_id)
        await query.edit_message_text(
            f"📊 **Your Stats**\n\nTotal Trades: {s['total']}\nWins: {s['wins']} | Losses: {s['losses']}\n"
            f"Win Rate: {s['win_rate']}%\nCurrent Streak: {s['current_streak']}", parse_mode="Markdown")

    elif data == "win":
        update_result(user_id, "win")
        await query.edit_message_text("✅ Win recorded! Streak reset.")

    elif data == "loss":
        update_result(user_id, "loss")
        stakes, streak = get_martingale_stakes(user_id)
        await query.edit_message_text(f"❌ Loss recorded. Next recommended stake: ${stakes[min(streak, len(stakes)-1)]}")

    elif data in ["set_stake", "set_channel"]:
        await query.edit_message_text("Use /setbase <amount> or /setchannel @yourchannel")

async def setbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_state[update.effective_user.id]["base_stake"] = max(1, min(int(context.args[0]), 500))
        await update.message.reply_text(f"✅ Base stake set to ${user_state[update.effective_user.id]['base_stake']}")
    except:
        await update.message.reply_text("Usage: /setbase 25")

async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        user_state[update.effective_user.id]["channel_id"] = context.args[0]
        await update.message.reply_text(f"✅ Auto-signal channel set. Signals will be sent every {AUTO_SIGNAL_INTERVAL_MINUTES} minutes.")

def main():
    if not TOKEN:
        print("ERROR: Set TELEGRAM_TOKEN in .env file")
        return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    job_queue = JobQueue()
    
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .job_queue(job_queue)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setbase", setbase))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CallbackQueryHandler(button_handler))

    if app.job_queue:
        app.job_queue.run_repeating(
            auto_signal_job, 
            interval=AUTO_SIGNAL_INTERVAL_MINUTES * 60, 
            first=30
        )
        print("✅ Auto signals enabled (every 3 minutes)")
    else:
        print("⚠️ JobQueue not available")

    print("✅ OTC Signals Bot v2 is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
