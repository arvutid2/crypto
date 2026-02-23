import os
import time
import requests
import pandas as pd
import numpy as np
import logging
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

class SentinelBotV10:
    def __init__(self):
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        self.symbol, self.alt_symbol = "BTCUSDT", "ETHUSDT"
        self.weights = {"rsi": 2.0, "bb_lower": 1.5, "trend_4h": 3.0, "fng": 1.0, "corr": 1.5, "macd": 2.5, "flow": 2.0}
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

    def add_indicators(self, df):
        # Baasindikaatorid
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + gain / loss))
        df['ema12'], df['ema26'] = df['close'].ewm(span=12).mean(), df['close'].ewm(span=26).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9).mean()
        df['ema200'] = df['close'].ewm(span=200).mean()
        
        # TURU REŽIIM (UUS!)
        # Arvutame ADX-stiilis trendi tugevuse
        df['high_low'] = df['high'] - df['low']
        df['atr'] = df['high_low'].rolling(window=14).mean()
        df['regime_strength'] = abs(df['close'] - df['close'].shift(14)) / (df['atr'] * 14)
        # Kui strength > 0.15, on turg trendis, muidu vahemikus
        df['market_regime'] = np.where(df['regime_strength'] > 0.18, "TRENDING", "RANGING")
        
        df['volatility'] = df['close'].rolling(window=20).std() / df['close'].rolling(window=20).mean()
        return df

    def get_last_buy_price(self):
        try:
            res = self.supabase.table("trade_logs").select("price").eq("action", "BUY").order("created_at", desc=True).limit(1).execute()
            return float(res.data[0]['price']) if res.data else None
        except: return None

    def start(self):
        logger.info("🌌 SENTINEL v10 - TRAILING & REGIME AWARE KÄIVITATUD")
        while True:
            try:
                df_btc = self.add_indicators(self.fetch_data(self.symbol, '1h'))
                df_eth = self.add_indicators(self.fetch_data(self.alt_symbol, '1h'))
                df_4h = self.add_indicators(self.fetch_data(self.symbol, '4h'))
                
                if df_btc is None: continue
                
                curr = df_btc.iloc[-1]
                regime = curr['market_regime']
                price = curr['close']
                
                # --- DÜNAAMILINE SKOORIMINE ---
                score = 0
                if regime == "RANGING":
                    if curr['rsi'] < 30: score += self.weights['rsi']
                else: # TRENDING - RSI on vähem tähtis, MACD ja 200 EMA on olulisemad
                    if curr['macd'] > curr['signal']: score += self.weights['macd'] * 1.2
                
                if price > df_4h.iloc[-1]['ema200']: score += self.weights['trend_4h']
                
                conf = round((score / sum(self.weights.values())) * 100, 2)
                
                # --- PORTFELL & OTSUS ---
                pf = self.supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
                usdt, btc_bal = float(pf['usdt_balance']), float(pf['btc_balance'])
                action, pnl_value, reason = "HOLD", None, "Ootel"

                buy_price = self.get_last_buy_price()

                # BUY LOOGIKA
                if usdt > 10 and conf >= 70 and (time.time() - self.last_trade_time) > self.cooldown:
                    action = "BUY"
                    self.supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": usdt/price}).eq("id", 1).execute()
                    self.last_trade_time = time.time()

                # SELL LOOGIKA (TRAILING)
                elif btc_bal > 0:
                    if buy_price:
                        pnl_value = round(((price - buy_price) / buy_price) * 100, 2)
                        
                        # Trailing Stop: Kui oleme plussis, aga MACD pöördub alla
                        if pnl_value > 1.5 and curr['macd'] < curr['signal']:
                            action = "SELL"
                            reason = "Trailing: Profit locked"
                        # Stop Loss
                        elif pnl_value < -3.0:
                            action = "SELL"
                            reason = "Stop Loss"
                        # Range müük
                        elif regime == "RANGING" and curr['rsi'] > 70:
                            action = "SELL"
                            reason = "RSI Overbought"

                    if action == "SELL":
                        self.supabase.table("portfolio").update({"usdt_balance": btc_bal*price, "btc_balance": 0}).eq("id", 1).execute()
                        self.last_trade_time = time.time()

                # SALVESTAMINE
                summary = f"Regime: {regime} | Conf: {conf}% | PnL: {pnl_value}% | {reason}"
                self.supabase.table("trade_logs").insert({
                    "symbol": self.symbol, "price": price, "rsi": curr['rsi'], "action": action,
                    "bot_confidence": conf, "pnl": pnl_value, "analysis_summary": summary
                }).execute()

                logger.info(f"V10 STATUS: {price} | {regime} | Conf: {conf}% | {action}")
                time.sleep(60)

            except Exception as e:
                logger.error(f"Viga: {e}")
                time.sleep(60)

if __name__ == "__main__":
    SentinelBotV10().start()