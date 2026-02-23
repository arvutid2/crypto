import os
import time
import requests
import pandas as pd
import numpy as np
import logging
from supabase import create_client
from dotenv import load_dotenv

# --- SEADISTUS & LOGIMINE ---
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - [%(module)s] %(message)s',
    handlers=[logging.FileHandler("bot_log.log"), logging.StreamHandler()]
)
logger = logging.getLogger()

class UltimateSentinelV11:
    def __init__(self):
        # Ühendus andmebaasiga
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        self.symbol = "BTCUSDT"
        self.alt_symbol = "ETHUSDT"
        
        # Kaalud otsustusprotsessis
        self.weights = {
            "rsi": 2.0, "bb_lower": 1.5, "trend_4h": 3.0, 
            "fng": 1.0, "eth_correlation": 1.5, "macd": 2.5, "order_flow": 2.0
        }
        
        # Trailing Stop-Lossi muutujad
        self.highest_price_since_buy = 0
        self.last_trade_time = 0
        self.cooldown = 300 

    def fetch_data(self, symbol, interval, limit=150):
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            data = requests.get(url, timeout=10).json()
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'ct', 'qav', 'nt', 'tb', 'tq', 'i'])
            df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
            return df
        except Exception as e:
            logger.error(f"Andmete laadimise viga ({symbol}): {e}")
            return None

    def get_order_book_pressure(self):
        try:
            url = f"https://api.binance.com/api/v3/depth?symbol={self.symbol}&limit=100"
            data = requests.get(url, timeout=5).json()
            bids = sum(float(quote[1]) for quote in data['bids'])
            asks = sum(float(quote[1]) for quote in data['asks'])
            return bids / asks if asks > 0 else 1.0
        except: return 1.0

    def get_fng(self):
        try:
            r = requests.get("https://api.alternative.me/fng/", timeout=5).json()
            return int(r['data'][0]['value'])
        except: return 50

    def add_indicators(self, df):
        if df is None: return None
        # 1. RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + gain / loss))
        
        # 2. MACD
        df['ema12'] = df['close'].ewm(span=12).mean()
        df['ema26'] = df['close'].ewm(span=26).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9).mean()
        
        # 3. Bollinger Bands & ATR
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['std20'] = df['close'].rolling(window=20).std()
        df['lower_band'] = df['sma20'] - (df['std20'] * 2)
        df['high_low'] = df['high'] - df['low']
        df['atr'] = df['high_low'].rolling(window=14).mean()
        
        # 4. Market Regime
        df['regime_strength'] = abs(df['close'] - df['close'].shift(14)) / (df['atr'] * 14)
        df['market_regime'] = np.where(df['regime_strength'] > 0.18, "TRENDING", "RANGING")
        
        # 5. Panic Filter
        df['avg_vol'] = df['vol'].rolling(window=20).mean()
        df['is_panic'] = (df['close'] < df['open']) & (df['vol'] > df['avg_vol'] * 2.5)
        
        return df

    def start(self):
        logger.info("🚀 ULTIMATE SENTINEL V11 ARVUTID2 EDITION STARTING...")
        
        while True:
            try:
                # 1. ANDMETE KOGUMINE
                df_btc = self.add_indicators(self.fetch_data(self.symbol, '1h'))
                df_eth = self.add_indicators(self.fetch_data(self.alt_symbol, '1h'))
                df_4h = self.add_indicators(self.fetch_data(self.symbol, '4h'))
                
                if df_btc is None or df_4h is None:
                    time.sleep(30)
                    continue

                fng = self.get_fng()
                pressure = self.get_order_book_pressure()
                curr = df_btc.iloc[-1]
                price = curr['close']
                regime = curr['market_regime']

                # 2. CONFIDENCE CALCULATION
                score = 0
                if regime == "RANGING":
                    if curr['rsi'] < 30: score += self.weights['rsi']
                else:
                    if curr['macd'] > curr['signal']: score += self.weights['macd']
                
                if price <= curr['lower_band']: score += self.weights['bb_lower']
                if df_4h.iloc[-1]['close'] > df_4h.iloc[-1]['ema200']: score += self.weights['trend_4h']
                if pressure > 1.2: score += self.weights['order_flow']
                if fng < 30: score += self.weights['fng']
                
                # ETH Correlation
                eth_curr = df_eth.iloc[-1]
                if (curr['close'] > curr['open'] and eth_curr['close'] > eth_curr['open']):
                    score += self.weights['eth_correlation']

                conf = round((score / sum(self.weights.values())) * 100, 2)

                # 3. PORTFELLI SEIS
                pf_res = self.supabase.table("portfolio").select("*").eq("id", 1).execute()
                if not pf_res.data:
                    logger.error("Portfelli andmeid ei leitud!")
                    continue
                
                pf = pf_res.data[0]
                usdt, btc_bal = float(pf['usdt_balance']), float(pf['btc_balance'])
                action, pnl_value, reason = "HOLD", None, "Market Analysis"

                # 4. OSTU LOOGIKA
                if usdt > 10 and not curr['is_panic'] and conf >= 70:
                    if (time.time() - self.last_trade_time) > self.cooldown:
                        action = "BUY"
                        self.highest_price_since_buy = price
                        # Dünaamiline positsioon: Osta kogu USDT eest
                        new_btc = usdt / price
                        self.supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": new_btc}).eq("id", 1).execute()
                        self.last_trade_time = time.time()
                        reason = f"High Confidence ({conf}%)"

                # 5. MÜÜGI LOOGIKA (TRAILING STOP & PROFIT)
                elif btc_bal > 0:
                    # Uuendame kõrgeimat hinda trailing stopi jaoks
                    if price > self.highest_price_since_buy:
                        self.highest_price_since_buy = price

                    # Võtame viimase ostuhinna
                    res = self.supabase.table("trade_logs").select("price").eq("action", "BUY").order("created_at", desc=True).limit(1).execute()
                    buy_price = float(res.data[0]['price']) if res.data else price
                    pnl_value = round(((price - buy_price) / buy_price) * 100, 2)

                    # Trailing Stop Calculation (1.5% langus tipust)
                    drop_from_peak = ((self.highest_price_since_buy - price) / self.highest_price_since_buy) * 100
                    
                    if pnl_value < -2.5:
                        action = "SELL"
                        reason = "Hard Stop Loss"
                    elif pnl_value > 1.0 and drop_from_peak > 1.2:
                        action = "SELL"
                        reason = "Trailing Stop-Loss Triggered"
                    elif regime == "RANGING" and curr['rsi'] > 70:
                        action = "SELL"
                        reason = "RSI Overbought in Range"

                    if action == "SELL":
                        new_usdt = btc_bal * price
                        self.supabase.table("portfolio").update({"usdt_balance": new_usdt, "btc_balance": 0}).eq("id", 1).execute()
                        self.last_trade_time = time.time()
                        self.highest_price_since_buy = 0

                # 6. SALVESTAMINE SUPABASE-I
                log_entry = {
                    "symbol": self.symbol, 
                    "price": price, 
                    "rsi": round(float(curr['rsi']), 2), 
                    "action": action,
                    "bot_confidence": conf, 
                    "market_pressure": round(pressure, 2), 
                    "fear_greed_index": fng,
                    "pnl": pnl_value, 
                    "is_panic_mode": bool(curr['is_panic']),
                    "analysis_summary": f"{regime} | Conf: {conf}% | PnL: {pnl_value}% | {reason}"
                }
                self.supabase.table("trade_logs").insert(log_entry).execute()

                logger.info(f"V11 Status: BTC ${price} | {action} | Conf: {conf}% | PnL: {pnl_value}%")
                
                # Ootame 1 minut enne uut tsüklit
                time.sleep(60)

            except Exception as e:
                logger.error(f"Süsteemne viga tsüklis: {e}")
                time.sleep(30)

if __name__ == "__main__":
    UltimateSentinelV11().start()