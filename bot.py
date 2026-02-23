import os
import time
import requests
import pandas as pd
import numpy as np
import logging
from supabase import create_client
from dotenv import load_dotenv

# --- SEADISTUS JA LOGIMINE ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

class UltimateGodBot:
    def __init__(self):
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        self.symbol = "BTCUSDT"
        self.alt_symbol = "ETHUSDT"
        
        self.weights = {
            "rsi": 2.5, "bb_lower": 1.5, "trend_4h": 3.0, 
            "fng": 1.0, "eth_correlation": 1.5, "macd": 2.5, "order_flow": 2.0
        }
        self.last_trade_time = 0
        self.cooldown = 300 

    def fetch_data(self, symbol, interval, limit=150):
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            data = requests.get(url, timeout=10).json()
            df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'ct', 'qav', 'nt', 'tb', 'tq', 'i'])
            df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
            return df
        except: return None

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
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + gain / loss))
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['std20'] = df['close'].rolling(window=20).std()
        df['lower_band'] = df['sma20'] - (df['std20'] * 2)
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['avg_vol'] = df['vol'].rolling(window=20).mean()
        df['is_panic'] = (df['close'] < df['open']) & (df['vol'] > df['avg_vol'] * 2.5)
        df['volatility'] = df['std20'] / df['sma20']
        return df

    def get_last_buy_price(self):
        """Leiab andmebaasist viimase eduka ostu hinna"""
        try:
            res = self.supabase.table("trade_logs").select("price").eq("action", "BUY").order("created_at", desc=True).limit(1).execute()
            if res.data:
                return float(res.data[0]['price'])
            return None
        except: return None

    def start(self):
        logger.info("🛡️ ULTIMATE GOD-MODE v9.2 - PnL TRACKING ON")
        
        while True:
            try:
                df_btc = self.add_indicators(self.fetch_data(self.symbol, '1h'))
                df_eth = self.add_indicators(self.fetch_data(self.alt_symbol, '1h'))
                df_4h = self.add_indicators(self.fetch_data(self.symbol, '4h'))
                fng = self.get_fng()
                pressure = self.get_order_book_pressure()
                
                if df_btc is None: continue

                curr_btc = df_btc.iloc[-1]
                prev_btc = df_btc.iloc[-2]
                price = curr_btc['close']

                # --- CONFIDENCE CALC ---
                score = 0
                if curr_btc['rsi'] < 30: score += self.weights['rsi']
                if price <= curr_btc['lower_band']: score += self.weights['bb_lower']
                if df_4h.iloc[-1]['close'] > df_4h.iloc[-1]['ema200']: score += self.weights['trend_4h']
                if curr_btc['macd'] > curr_btc['signal']: score += self.weights['macd']
                if pressure > 1.2: score += self.weights['order_flow']
                if fng < 30: score += self.weights['fng']
                
                btc_move = (curr_btc['close'] - curr_btc['open']) / curr_btc['open']
                eth_move = (df_eth.iloc[-1]['close'] - df_eth.iloc[-1]['open']) / df_eth.iloc[-1]['open']
                corr_ok = (btc_move > 0 and eth_move > 0) or (btc_move < 0 and eth_move < 0)
                if corr_ok: score += self.weights['eth_correlation']

                conf = round((score / sum(self.weights.values())) * 100, 2)
                
                # --- TRADE LOGIC ---
                pf = self.supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
                usdt, btc_bal = float(pf['usdt_balance']), float(pf['btc_balance'])
                action, pnl_value = "HOLD", None

                current_time = time.time()
                can_trade = (current_time - self.last_trade_time) > self.cooldown

                if usdt > 10 and not curr_btc['is_panic'] and conf >= 72 and can_trade:
                    if price > prev_btc['low']:
                        action = "BUY"
                        self.supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": usdt/price}).eq("id", 1).execute()
                        self.last_trade_time = current_time

                elif btc_bal > 0 and (curr_btc['rsi'] > 70 or pressure < 0.7 or fng > 80):
                    action = "SELL"
                    # ARVUTAME PnL
                    buy_price = self.get_last_buy_price()
                    if buy_price:
                        pnl_value = round(((price - buy_price) / buy_price) * 100, 2)
                    
                    self.supabase.table("portfolio").update({"usdt_balance": btc_bal*price, "btc_balance": 0}).eq("id", 1).execute()
                    self.last_trade_time = current_time

                # --- SALVESTAMINE ---
                total_val = usdt + (btc_bal * price)
                self.supabase.table("portfolio").update({"total_value_usdt": total_val}).eq("id", 1).execute()
                
                self.supabase.table("trade_logs").insert({
                    "symbol": self.symbol, "price": price, "rsi": curr_btc['rsi'], 
                    "action": action, "bot_confidence": conf, "market_pressure": pressure, 
                    "fear_greed_index": fng, "is_panic_mode": bool(curr_btc['is_panic']),
                    "pnl": pnl_value, # Nüüd saadetakse siia reaalne number!
                    "analysis_summary": f"Conf: {conf}% | Press: {round(pressure,2)} | PnL: {pnl_value}%"
                }).execute()

                logger.info(f"STATUS: {price} | Conf: {conf}% | PnL: {pnl_value} | {action}")
                time.sleep(60)

            except Exception as e:
                logger.error(f"Viga: {e}")
                time.sleep(60)

if __name__ == "__main__":
    UltimateGodBot().start()