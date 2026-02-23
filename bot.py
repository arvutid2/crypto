import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import logging
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv

# 1. SEADISTUS JA LOGID
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

SYMBOL = 'BTCUSDT'
last_buy_price = None

# 2. SEADETE PÄRIMINE (DÜNAAMILINE)
def get_bot_settings():
    try:
        res = supabase.table("bot_settings").select("*").eq("id", 1).single().execute()
        return res.data if res.data else {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}
    except:
        return {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}

# 3. TURU ANDMED + KÕIK INDIKAATORID (MACD, BB, ATR, EMA)
def get_market_data(symbol):
    try:
        klines = client.get_historical_klines(symbol, '1m', "500 minutes ago UTC")
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        # RSI
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # MACD (indeksite põhjal, et vältida nimevigu)
        macd = ta.macd(df['close'])
        df['macd'] = macd.iloc[:, 0]
        df['macd_signal'] = macd.iloc[:, 2]
        
        # Bollinger Bands (indeksite põhjal)
        bbands = ta.bbands(df['close'], length=20, std=2)
        df['bb_lower'] = bbands.iloc[:, 0]
        df['bb_upper'] = bbands.iloc[:, 2]
        
        # Keskmised
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        # ATR
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
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
        res = requests.get("https://api.alternative.me/fng/").json()
        return int(res['data'][0]['value'])
    except: return 50

# 4. SIGNAALIDE ANALÜÜS
def analyze_signals(df):
    global last_buy_price
    settings = get_bot_settings()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    rsi = curr['rsi']
    macd = curr['macd']
    macd_s = curr['macd_signal']
    
    # AI ENNUSTUS
    prediction = 0.5
    pressure = get_order_book_status(SYMBOL)
    fng = get_fear_greed()
    
    if os.path.exists('trading_brain.pkl'):
        try:
            model = joblib.load('trading_brain.pkl')
            # SAMA JÄRJEKORD MIS BRAIN.PY SEES!
            input_data = pd.DataFrame([[
                price, rsi, macd, macd_s, 
                curr['bb_upper'], curr['bb_lower'], curr['atr'], curr['ema200'],
                pressure, fng
            ]], columns=['price', 'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr', 'ema200', 'market_pressure', 'fear_greed_index'])
            prediction = model.predict(input_data)[0]
        except Exception as e:
            logger.error(f"AI vea ennustus: {e}")

    action = "HOLD"
    summary = ""
    pnl = 0

    # OSTU REEGEL
    if last_buy_price is None:
        ai_bullish = prediction >= float(settings['min_ai_confidence'])
        macd_bullish = macd > macd_s and prev['macd'] <= prev['macd_signal']
        
        # Agressiivne sisenemine: AI on kindel JA (MACD kross VÕI RSI ülimadal)
        if ai_bullish and (macd_bullish or rsi < 30):
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 BUY | AI:{prediction} | RSI:{rsi:.1f}"

    # MÜÜGI REEGEL
    elif last_buy_price is not None:
        pnl = ((price - last_buy_price) / last_buy_price) * 100
        sl_limit = float(settings['stop_loss'])
        tp_limit = float(settings['take_profit'])
        
        if pnl <= sl_limit or pnl >= tp_limit:
            action = "SELL"
            summary = f"🛑 EXIT (SL/TP): {pnl:.2f}%"
            last_buy_price = None
        elif rsi > 75 or (macd < macd_s and rsi > 60):
            action = "SELL"
            summary = f"💰 STRATEGIC SELL: {pnl:.2f}%"
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | RSI:{rsi:.1f} | AI:{prediction} | MACD:{'UP' if macd > macd_s else 'DOWN'}"

    return action, summary, pnl, prediction

# 5. LOGIMINE
def log_to_supabase(action, df, pnl, summary, prediction):
    try:
        curr = df.iloc[-1]
        fng = get_fear_greed()
        pressure = get_order_book_status(SYMBOL)
        
        supabase.table("trade_logs").insert({
            "symbol": SYMBOL,
            "action": action,
            "price": float(curr['close']),
            "rsi": float(curr['rsi']),
            "macd": float(curr['macd']),
            "macd_signal": float(curr['macd_signal']),
            "bb_upper": float(curr['bb_upper']),
            "bb_lower": float(curr['bb_lower']),
            "atr": float(curr['atr']),
            "ema200": float(curr['ema200']),
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
    logger.info(f"🤖 Bot Targem V18 Online: {SYMBOL}")
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, pnl, prediction = analyze_signals(df)
                log_to_supabase(action, df, pnl, summary, prediction)
                if action != "HOLD": 
                    logger.info(f"🔔 {summary}")
                else: 
                    print(f"[{time.strftime('%H:%M:%S')}] {summary}", end='\r')
            time.sleep(30)
        except Exception as e:
            logger.error(f"Viga põhitsüklis: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()