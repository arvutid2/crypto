import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import logging
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv

# 1. LOGIMISE SEADISTUS
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [bot] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Ühendused
try:
    client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
    supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
    logger.info("✅ Ühendused Binance'i ja Supabase'iga loodud.")
except Exception as e:
    logger.error(f"❌ Ühenduse viga: {e}")

SYMBOL = 'BTCUSDT'
last_buy_price = None

def get_bot_settings():
    try:
        res = supabase.table("bot_settings").select("*").eq("id", 1).single().execute()
        return res.data if res.data else {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}
    except:
        return {"stop_loss": -2.0, "take_profit": 3.0, "min_ai_confidence": 0.6}

# 2. ANDMETE KOGUMINE JA INDIKAATORID
def get_market_data(symbol):
    try:
        # Tõmbame piisavalt andmeid, et indikaatorid (eriti EMA200) arvutuksid õigesti
        klines = client.get_historical_klines(symbol, '1m', "500 minutes ago UTC")
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        # --- TEHNILINE ANALÜÜS ---
        
        # RSI ja MACD
        df['rsi'] = ta.rsi(df['close'], length=14)
        macd = ta.macd(df['close'])
        df['macd'] = macd.iloc[:, 0]
        df['macd_signal'] = macd.iloc[:, 2]
        
        # Bollinger Bands (Sinu pildil olid need NULL-id, parandame siin)
        bbands = ta.bbands(df['close'], length=20, std=2)
        if bbands is not None:
            df['bb_lower'] = bbands.iloc[:, 0]
            df['bb_upper'] = bbands.iloc[:, 2]
        else:
            df['bb_lower'] = df['close'] * 0.98 # Avarii-väärtus, et vältida NULL-i
            df['bb_upper'] = df['close'] * 1.02

        # VWAP (Vajab ajaindeksit)
        df['time_dt'] = pd.to_datetime(df['time'], unit='ms')
        df.set_index('time_dt', inplace=True)
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        df.reset_index(inplace=True)
        
        # Stochastic Oscillator
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        if stoch is not None:
            df['stoch_k'] = stoch.iloc[:, 0]
            df['stoch_d'] = stoch.iloc[:, 1]
        
        # ATR ja EMA
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        return df
    except Exception as e:
        logger.error(f"❌ Viga indikaatorite arvutamisel: {e}")
        return None

def get_order_book_status(symbol):
    try:
        depth = client.get_order_book(symbol=symbol, limit=10)
        bids = sum([float(p) * float(q) for p, q in depth['bids']])
        asks = sum([float(p) * float(q) for p, q in depth['asks']])
        return bids / asks
    except: return 1.0

# 3. OTSUSTAMISE LOOGIKA
def analyze_signals(df):
    global last_buy_price
    settings = get_bot_settings()
    
    curr = df.iloc[-1]
    price = curr['close']
    
    # Algsätted
    prediction = 0.5
    pressure = get_order_book_status(SYMBOL)
    
    # Mudeli laadimine
    if os.path.exists('trading_brain_xgb.pkl'):
        try:
            model = joblib.load('trading_brain_xgb.pkl')
            # NB! Peab ühtima brain.py features listiga
            features = [
                float(price), float(curr['rsi']), float(curr['macd']), float(curr['macd_signal']),
                float(curr['vwap']), float(curr['stoch_k']), float(curr['stoch_d']),
                float(curr['atr']), float(curr['ema200']), float(pressure)
            ]
            prediction = model.predict_proba([features])[0][1]
        except Exception as e:
            logger.warning(f"Mudeli ennustus ebaõnnestus: {e}")

    action = "HOLD"
    summary = ""
    pnl = 0

    # OSTMINE
    if last_buy_price is None:
        threshold = float(settings.get('min_ai_confidence', 0.6))
        if prediction >= threshold and curr['stoch_k'] < 30:
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 BUY | AI:{prediction:.2f} | Stoch:{curr['stoch_k']:.1f}"

    # MÜÜMINE
    elif last_buy_price is not None:
        pnl = ((price - last_buy_price) / last_buy_price) * 100
        if pnl <= float(settings.get('stop_loss', -2.0)) or pnl >= float(settings.get('take_profit', 3.0)):
            action = "SELL"
            summary = f"💰 SELL | PnL:{pnl:.2f}%"
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | Price:{price} | AI:{prediction:.2f} | Stoch:{curr['stoch_k']:.1f}"

    return action, summary, pnl, prediction

# 4. SALVESTAMINE
def log_to_supabase(action, df, pnl, summary, prediction):
    try:
        curr = df.iloc[-1]
        pressure = get_order_book_status(SYMBOL)
        
        # Kontrollime väärtusi enne saatmist (pd.isna asendab NULL-id 0.0-ga)
        def clean(val):
            return float(val) if not pd.isna(val) else 0.0

        data = {
            "symbol": SYMBOL,
            "action": action,
            "price": clean(curr['close']),
            "rsi": clean(curr['rsi']),
            "macd": clean(curr['macd']),
            "macd_signal": clean(curr['macd_signal']),
            "vwap": clean(curr['vwap']),
            "stoch_k": clean(curr['stoch_k']),
            "stoch_d": clean(curr['stoch_d']),
            "bb_upper": clean(curr['bb_upper']),
            "bb_lower": clean(curr['bb_lower']),
            "atr": clean(curr['atr']),
            "ema200": clean(curr['ema200']),
            "volume": clean(curr['volume']),
            "pnl": float(pnl),
            "analysis_summary": summary,
            "market_pressure": clean(pressure),
            "ai_prediction": float(prediction)
        }
        supabase.table("trade_logs").insert(data).execute()
    except Exception as e:
        logger.error(f"❌ Logimise viga: {e}")

def run_bot():
    logger.info(f"🤖 Bot V2.1 käivitatud sümbooliga {SYMBOL}")
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, pnl, prediction = analyze_signals(df)
                log_to_supabase(action, df, pnl, summary, prediction)
                
                if action != "HOLD": 
                    logger.info(f"🔔 TEHING: {summary}")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] {summary}", end='\r')
            
            time.sleep(30)
        except Exception as e:
            logger.error(f"Põhitsükli viga: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()