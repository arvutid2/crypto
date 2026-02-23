import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import logging
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

SYMBOL = 'BTCUSDT'
last_buy_price = None

def get_bot_settings():
    try:
        res = supabase.table("bot_settings").select("*").eq("id", 1).single().execute()
        return res.data if res.data else {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}
    except:
        return {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}

def get_market_data(symbol):
    try:
        klines = client.get_historical_klines(symbol, '1m', "300 minutes ago UTC")
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        df[['open', 'close', 'volume']] = df[['open', 'close', 'volume']].apply(pd.to_numeric)
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema50'] = ta.ema(df['close'], length=50)
        return df
    except Exception as e:
        logger.error(f"Andmete viga: {e}")
        return None

def get_order_book_status(symbol):
    try:
        depth = client.get_order_book(symbol=symbol, limit=10)
        bids = sum([float(p) * float(q) for p, q in depth['bids']])
        asks = sum([float(p) * float(q) for p, q in depth['asks']])
        return bids / asks
    except: return 1.0

def get_fear_greed():
    try:
        import requests
        return int(requests.get("https://api.alternative.me/fng/").json()['data'][0]['value'])
    except: return 50

def analyze_signals(df):
    global last_buy_price
    settings = get_bot_settings()
    
    curr = df.iloc[-1]
    price = curr['close']
    rsi = curr['rsi']
    
    # AI ENNUSTUS
    prediction = 0.5
    if os.path.exists('trading_brain.pkl'):
        try:
            model = joblib.load('trading_brain.pkl')
            pressure = get_order_book_status(SYMBOL)
            fng = get_fear_greed()
            input_data = pd.DataFrame([[price, rsi, pressure, fng]], 
                                     columns=['price', 'rsi', 'market_pressure', 'fear_greed_index'])
            prediction = model.predict(input_data)[0]
        except: pass

    action = "HOLD"
    summary = ""
    pnl = 0

    # OSTU REEGEL (Agressiivsem)
    if last_buy_price is None:
        # Kui AI on kindel (1.0) ja RSI on ülimadal (<30), siis siseneme!
        if (prediction >= float(settings['min_ai_confidence']) and rsi < 30) or \
           (price > curr['ema50'] and prediction >= 0.7):
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 BUY | AI:{prediction} | RSI:{rsi:.1f}"

    # MÜÜGI REEGEL
    elif last_buy_price is not None:
        pnl = ((price - last_buy_price) / last_buy_price) * 100
        if pnl <= float(settings['stop_loss']) or pnl >= float(settings['take_profit']):
            action = "SELL"
            summary = f"💰 SELL | PnL:{pnl:.2f}%"
            last_buy_price = None
        elif rsi > 70:
            action = "SELL"
            summary = f"💰 RSI SELL | PnL:{pnl:.2f}%"
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | RSI:{rsi:.1f} | AI:{prediction} | SL:{settings['stop_loss']}%"

    return action, summary, pnl, prediction

def log_to_supabase(action, price, rsi, pnl, summary, prediction):
    try:
        fng = get_fear_greed()
        pressure = get_order_book_status(SYMBOL)
        supabase.table("trade_logs").insert({
            "symbol": SYMBOL,
            "action": action,
            "price": float(price),
            "rsi": float(rsi),
            "pnl": float(pnl),
            "analysis_summary": summary,
            "market_pressure": float(pressure),
            "fear_greed_index": int(fng),
            "ai_prediction": float(prediction),
            "bot_confidence": float(prediction),
            "is_panic_mode": False
        }).execute()
    except Exception as e:
        logger.error(f"Logi viga: {e}")

def run_bot():
    logger.info(f"🤖 Bot Online: {SYMBOL}")
    while True:
        df = get_market_data(SYMBOL)
        if df is not None:
            action, summary, pnl, prediction = analyze_signals(df)
            log_to_supabase(action, df.iloc[-1]['close'], df.iloc[-1]['rsi'], pnl, summary, prediction)
            if action != "HOLD": logger.info(f"🔔 {summary}")
            else: print(f"[{time.strftime('%H:%M:%S')}] {summary}", end='\r')
        time.sleep(30)

if __name__ == "__main__":
    run_bot()