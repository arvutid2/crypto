import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import logging
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv

# 1. LOGIMINE JA SEADISTUS
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Ühendused
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Sümbol ja seaded
SYMBOL = 'BTCUSDT'
last_buy_price = None

# 2. DÜNAAMILISTE SEADETE PÄRIMINE
def get_bot_settings():
    try:
        res = supabase.table("bot_settings").select("*").eq("id", 1).single().execute()
        if res.data:
            return res.data
    except Exception as e:
        logger.error(f"Viga seadete lugemisel: {e}")
    
    # Vaikimisi seaded, kui andmebaasist kätte ei saa
    return {
        "stop_loss": -2.0,
        "take_profit": 3.0,
        "min_ai_confidence": 0.6
    }

# 3. TURU ANDMETE PÄRIMINE
def get_market_data(symbol, interval='1m', limit=300):
    try:
        klines = client.get_historical_klines(symbol, interval, f"{limit} minutes ago UTC")
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        df['close'] = df['close'].astype(float)
        df['open'] = df['open'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # Indikaatorid
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        return df
    except Exception as e:
        logger.error(f"Viga andmete pärimisel: {e}")
        return None

# 4. MARKET PRESSURE (Order Book)
def get_order_book_status(symbol):
    try:
        depth = client.get_order_book(symbol=symbol, limit=20)
        bids = sum([float(price) * float(qty) for price, qty in depth['bids']])
        asks = sum([float(price) * float(qty) for price, qty in depth['asks']])
        ratio = bids / asks
        return bids > asks, ratio
    except:
        return True, 1.0

# 5. FEAR & GREED INDEX
def get_fear_greed():
    try:
        import requests
        res = requests.get("https://api.alternative.me/fng/").json()
        return int(res['data'][0]['value'])
    except:
        return 50

# 6. SIGNAALIDE ANALÜÜS (DÜNAAMILINE)
def analyze_signals(df):
    global last_buy_price
    
    # Loeme värsked seaded andmebaasist (SL, TP, AI Confidence)
    settings = get_bot_settings()
    sl_limit = float(settings['stop_loss'])
    tp_limit = float(settings['take_profit'])
    min_conf = float(settings['min_ai_confidence'])

    if df is None or len(df) < 200:
        return "HOLD", "Kogume ajalugu...", 0, 1.0, 0.5

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    rsi = curr['rsi']
    
    # AI ENNUSTUS
    prediction = 0.5
    if os.path.exists('trading_brain.pkl'):
        try:
            model = joblib.load('trading_brain.pkl')
            # Kasutame samu feature'id mis brain.py-s
            fng = get_fear_greed()
            _, pressure = get_order_book_status(SYMBOL)
            input_data = pd.DataFrame([[price, rsi, pressure, fng]], 
                                     columns=['price', 'rsi', 'market_pressure', 'fear_greed_index'])
            prediction = model.predict(input_data)[0]
        except: pass

    is_green = curr['close'] > curr['open']
    bullish_book, book_ratio = get_order_book_status(SYMBOL)
    
    action = "HOLD"
    summary = ""
    profit_pct = 0

    # --- OSTU LOOGIKA ---
    if last_buy_price is None:
        # Kombineeritud: AI kindlus VÕI Tehniline trend
        if (prediction >= min_conf and price > curr['ema50'] and is_green) or \
           (price > curr['ema50'] > curr['ema200'] and rsi < 45 and is_green):
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 BUY | AI:{prediction} | Conf:{min_conf}"

    # --- MÜÜGI LOOGIKA (DÜNAAMILINE) ---
    elif last_buy_price is not None:
        profit_pct = ((price - last_buy_price) / last_buy_price) * 100
        
        # 1. DÜNAAMILINE STOP-LOSS
        if profit_pct <= sl_limit:
            action = "SELL"
            summary = f"🛑 DYNAMIC SL: {profit_pct:.2f}% (Limit: {sl_limit}%)"
            last_buy_price = None

        # 2. DÜNAAMILINE TAKE-PROFIT
        elif profit_pct >= tp_limit:
            action = "SELL"
            summary = f"🎯 DYNAMIC TP: {profit_pct:.2f}% (Limit: {tp_limit}%)"
            last_buy_price = None

        # 3. SIGNAALI PÕHJAL MÜÜK
        elif rsi > 70 or (prediction == 0 and rsi > 55):
            action = "SELL"
            summary = f"💰 SIGNAL SELL: {profit_pct:.2f}% | AI:{prediction}"
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | RSI:{rsi:.1f} | AI:{prediction} | SL:{sl_limit}%"

    return action, summary, profit_pct, book_ratio, prediction

# 7. LOGIMINE SUPABASE-I
def log_to_supabase(action, price, rsi, pnl, summary, pressure, fng, prediction):
    try:
        supabase.table("trade_logs").insert({
            "action": action,
            "price": price,
            "rsi": rsi,
            "pnl": pnl,
            "analysis_summary": summary,
            "market_pressure": pressure,
            "fear_greed_index": fng,
            "ai_prediction": float(prediction)
        }).execute()
    except Exception as e:
        logger.error(f"Supabase logi viga: {e}")

# 8. PÕHITSÜKKEL
def run_bot():
    logger.info(f"🤖 Bot V17 käivitatud sümboliga {SYMBOL}")
    
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, pnl, pressure, prediction = analyze_signals(df)
                curr_price = df.iloc[-1]['close']
                curr_rsi = df.iloc[-1]['rsi']
                fng = get_fear_greed()
                
                # Logime iga sammu
                log_to_supabase(action, curr_price, curr_rsi, pnl, summary, pressure, fng, prediction)
                
                if action != "HOLD":
                    logger.info(f"🔔 ACTION: {summary}")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] {summary}", end='\r')

            time.sleep(30)
        except Exception as e:
            logger.error(f"Viga tsüklis: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()