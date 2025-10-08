import asyncio
import aiohttp
import pandas as pd
import mplfinance as mpf
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ----------------- توکن ربات -----------------
TOKEN = "8222728657:AAFxnkpUtVkd4eQb2gAqLXuu5ExGEO6UmFQ"

# ----------------- تنظیمات API -----------------
API_BASE = "https://api.toobit.com"
KLINES = API_BASE + "/quote/v1/klines"
TICKERS = API_BASE + "/quote/v1/ticker/price"

INTERVAL_15M = "15m"
INTERVAL_1H = "1h"
LIMIT_15M = 100
LIMIT_1H = 100
BATCH_SIZE = 50
MAX_CHARTS = 15  # حداکثر تعداد چارت‌ها

# ----------------- توابع کمک کننده -----------------
async def get_symbols(session):
    async with session.get(TICKERS, timeout=10) as r:
        data = await r.json()
        return [s["s"] for s in data if s["s"].endswith("USDT")]

async def get_klines(session, symbol, interval, limit):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    async with session.get(KLINES, params=params, timeout=10) as r:
        data = await r.json()
        df = pd.DataFrame(data)
        if df.empty or df.shape[1] < 6:
            return None
        df = df.iloc[:, :6]
        df.columns = ["open_time","open","high","low","close","volume"]
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        return df

async def detect_cross(session, symbol, interval):
    try:
        df = await get_klines(session, symbol, interval, LIMIT_1H if interval=="1h" else LIMIT_15M)
        if df is None: return None

        # EMA20 و EMA50
        ema20 = df["close"].ewm(span=20, adjust=False).mean()
        ema50 = df["close"].ewm(span=50, adjust=False).mean()
        df["EMA20"] = ema20
        df["EMA50"] = ema50

        # فقط سه کندل آخر بررسی شود
        df_last = df.iloc[-3:]
        prev_ema20, prev_ema50 = df_last["EMA20"].iloc[-2], df_last["EMA50"].iloc[-2]
        last_ema20, last_ema50 = df_last["EMA20"].iloc[-1], df_last["EMA50"].iloc[-1]

        cross_up = prev_ema20 < prev_ema50 and last_ema20 > last_ema50
        cross_down = prev_ema20 > prev_ema50 and last_ema20 < last_ema50

        if cross_up or cross_down:
            direction = "bullish" if cross_up else "bearish"
            return {"symbol": symbol, "df": df, "direction": direction}
        return None
    except:
        return None

async def run_scan(interval):
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        symbols = await get_symbols(session)
        results = []
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i+BATCH_SIZE]
            tasks = [detect_cross(session, sym, interval) for sym in batch]
            batch_results = await asyncio.gather(*tasks)
            for r in batch_results:
                if r:
                    results.append(r)
                    if len(results) >= MAX_CHARTS:
                        return results
        return results

# ----------------- دستورات ربات -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 EMA50 & EMA20 1H (سه کندل آخر)", callback_data="1h")],
        [InlineKeyboardButton("📊 EMA50 & EMA20 15M (سه کندل آخر)", callback_data="15m")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("سلام 👋\nیکی از گزینه‌ها را انتخاب کن:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    interval = query.data
    await query.edit_message_text(f"⏳ در حال اسکن ({interval}) ...")
    results = await run_scan(interval)
    if not results:
        await query.message.reply_text(f"❌ هیچ کراسی پیدا نشد.")
        return

    # --- متن لیست ---
    text = f"✅ کراس‌های پیدا شده ({interval}):\n"
    for r in results:
        text += f"📈 {r['symbol']} → {r['direction']}\n"
    await query.message.reply_text(text)

    # --- نمودار کندلی ---
    for r in results:
        df = r["df"]
        symbol = r["symbol"]
        filename = f"{symbol}_{interval}_candle.jpg"
        addplot = [
            mpf.make_addplot(df["EMA20"], color="orange", width=1.2),
            mpf.make_addplot(df["EMA50"], color="blue", width=1.2)
        ]
        mpf.plot(df, type="candle", style="charles",
                 title=f"{symbol} {interval} EMA20 & EMA50",
                 volume=True,
                 addplot=addplot,
                 savefig=filename, show_nontrading=False)
        await query.message.reply_photo(open(filename,"rb"))
        await asyncio.sleep(1)

# ----------------- اجرای ربات -----------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()

if __name__ == "__main__":
    main()
