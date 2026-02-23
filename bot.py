import os
import time
import pandas as pd
import pandas_ta as ta
import joblib
import logging
from binance.client import Client
from supabase import create_client
from dotenv import load_dotenv

# 1. SEADISTUS
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

# 2. RIKALIKUD ANDMED JA INDIKAATORID
def get_market_data(symbol):
    try:
        # Küsime piisavalt ajalugu indikaatorite jaoks
        klines = client.get_historical_klines(symbol, '1m', "500 minutes ago UTC")
        df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        # Standard: RSI ja MACD
        df['rsi'] = ta.rsi(df['close'], length=14)
        macd = ta.macd(df['close'])
        df['macd'] = macd.iloc[:, 0]
        df['macd_signal'] = macd.iloc[:, 2]
        
        # Trend: VWAP (Vajab aega, hinda ja mahtu)
        # Teisendame aja datetime formaati VWAP-i jaoks
        df['time_dt'] = pd.to_datetime(df['time'], unit='ms')
        df.set_index('time_dt', inplace=True)
        df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        df.reset_index(inplace=True)
        
        # Momentum: Stochastic Oscillator
        stoch = ta.stoch(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.iloc[:, 0]
        df['stoch_d'] = stoch.iloc[:, 1]
        
        # Volatiilsus ja keskmised
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        # Bollinger Bands (Alumise bändi jaoks)
        bbands = ta.bbands(df['close'], length=20, std=2)
        df['bb_lower'] = bbands.iloc[:, 0]
        df['bb_upper'] = bbands.iloc[:, 2]
        
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

# 3. ANALÜÜS (XGBOOST ÜHILDUVUS)
def analyze_signals(df):
    global last_buy_price
    settings = get_bot_settings()
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    
    # Ennustus ja sentiment
    prediction = 0.5
    pressure = get_order_book_status(SYMBOL)
    fng = get_fear_greed()
    
    # XGBoost Mudeli laadimine (V2)
    if os.path.exists('trading_brain_xgb.pkl'):
        try:
            model = joblib.load('trading_brain_xgb.pkl')
            # NB! Järjekord peab ühtima brain.py-ga
            features = [
                price, curr['rsi'], curr['macd'], curr['macd_signal'],
                curr['vwap'], curr['stoch_k'], curr['stoch_d'],
                curr['atr'], curr['ema200'], pressure, fng
            ]
            # XGBoost eeldab 2D maatriksit
            prediction = model.predict_proba([features])[0][1]
        except:
            pass

    action = "HOLD"
    summary = ""
    pnl = 0

    # OSTU REEGEL (XGBoost + Tehniline kinnitus)
    if last_buy_price is None:
        ai_threshold = float(settings.get('min_ai_confidence', 0.6))
        
        # Kombineeritud signaal: AI on kindel JA Stochastik on oversold (<20)
        if prediction >= ai_threshold and curr['stoch_k'] < 25:
            action = "BUY"
            last_buy_price = price
            summary = f"🚀 XGB BUY | AI:{prediction:.2f} | Stoch:{curr['stoch_k']:.1f}"

    # MÜÜGI REEGEL
    elif last_buy_price is not None:
        pnl = ((price - last_buy_price) / last_buy_price) * 100
        sl = float(settings.get('stop_loss', -2.0))
        tp = float(settings.get('take_profit', 3.0))
        
        if pnl <= sl or pnl >= tp or curr['stoch_k'] > 80:
            action = "SELL"
            summary = f"💰 EXIT | PnL:{pnl:.2f}% | Stoch:{curr['stoch_k']:.1f}"
            last_buy_price = None

    if action == "HOLD":
        summary = f"HOLD | RSI:{curr['rsi']:.1f} | AI:{prediction:.2f} | VWAP:{'UP' if price > curr['vwap'] else 'DOWN'}"

    return action, summary, pnl, prediction

# 4. LOGIMINE SUPABASE'I
def log_to_supabase(action, df, pnl, summary, prediction):
    try:
        curr = df.iloc[-1]
        fng = get_fear_greed()
        pressure = get_order_book_status(SYMBOL)
        
        data = {
            "symbol": SYMBOL,
            "action": action,
            "price": float(curr['close']),
            "rsi": float(curr['rsi']),
            "macd": float(curr['macd']),
            "macd_signal": float(curr['macd_signal']),
            "vwap": float(curr['vwap']),
            "stoch_k": float(curr['stoch_k']),
            "stoch_d": float(curr['stoch_d']),
            "atr": float(curr['atr']),
            "ema200": float(curr['ema200']),
            "volume": float(curr['volume']),
            "pnl": float(pnl),
            "analysis_summary": summary,
            "market_pressure": float(pressure),
            "fear_greed_index": int(fng),
            "ai_prediction": float(prediction),
            "bot_confidence": float(prediction)
        }
        supabase.table("trade_logs").insert(data).execute()
    except Exception as e:
        logger.error(f"Logi viga: {e}")

def run_bot():
    logger.info(f"🤖 Bot V2 (XGBoost Ready) Online: {SYMBOL}")
    while True:
        try:
            df = get_market_data(SYMBOL)
            if df is not None:
                action, summary, pnl, prediction = analyze_signals(df)
                log_to_supabase(action, df, pnl, summary, prediction)
                if action != "HOLD": logger.info(f"🔔 {summary}")
                else: print(f"[{time.strftime('%H:%M:%S')}] {summary}", end='\r')
            time.sleep(30)
        except Exception as e:
            logger.error(f"Viga: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()