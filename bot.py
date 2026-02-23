import os
import time
import requests
import pandas as pd
import numpy as np
import logging
from supabase import create_client
from dotenv import load_dotenv

# --- SEADISTUS ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

class UltimateGodBot:
    def __init__(self):
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        self.symbol = "BTCUSDT"
        self.alt_symbol = "ETHUSDT"
        
        # KÕIK KAALUD ON ALLES JA KOOS
        self.weights = {
            "rsi": 2.5,
            "bb_lower": 1.5,
            "trend_4h": 3.0,
            "fng": 1.0,
            "eth_correlation": 1.5,
            "macd": 2.5,
            "order_flow": 2.0
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
        except Exception as e:
            logger.error(f"Andmete viga ({symbol}): {e}")
            return None

    def get_order_book_pressure(self):
        try:
            url = f"https://api.binance.com/api/v3/depth?symbol={self.symbol}&limit=100"
            data = requests.get(url, timeout=5).json()
            bids = sum(float(quote[1]) for quote in data['bids'])
            asks = sum(float(quote[1]) for quote in data['asks'])
            return bids / asks
        except: return 1.0

    def add_indicators(self, df):
        # 1. RSI (Klassika)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['rsi'] = 100 - (100 / (1 + gain / loss))

        # 2. MACD (Trendi kiirus)
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # 3. Bollinger Bands (Hinna piirid)
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['std20'] = df['close'].rolling(window=20).std()
        df['lower_band'] = df['sma20'] - (df['std20'] * 2)
        df['upper_band'] = df['sma20'] + (df['std20'] * 2)

        # 4. Trendid ja Paanika
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['avg_vol'] = df['vol'].rolling(window=20).mean()
        df['is_panic'] = (df['close'] < df['open']) & (df['vol'] > df['avg_vol'] * 2.5)
        df['volatility'] = df['std20'] / df['sma20']
        
        return df

    def get_fng(self):
        try:
            return int(requests.get("https://api.alternative.me/fng/").json()['data'][0]['value'])
        except: return 50

    def start(self):
        logger.info("🚀 ULTIMATE GOD-MODE BOT KÄIVITATUD!")
        
        while True:
            try:
                # 1. ANDMETE KOGUMINE
                df_btc = self.add_indicators(self.fetch_data(self.symbol, '1h'))
                df_eth = self.add_indicators(self.fetch_data(self.alt_symbol, '1h'))
                df_4h = self.add_indicators(self.fetch_data(self.symbol, '4h'))
                fng = self.get_fng()
                pressure = self.get_order_book_pressure()
                
                if df_btc is None or df_eth is None: continue

                curr_btc = df_btc.iloc[-1]
                prev_btc = df_btc.iloc[-2]
                curr_eth = df_eth.iloc[-1]
                curr_4h = df_4h.iloc[-1]
                price = curr_btc['close']

                # 2. ANALÜÜS JA PUNKTIARVESTUS
                score = 0
                
                # RSI punktid
                if curr_btc['rsi'] < 30: score += self.weights['rsi']
                # Bollinger punktid
                if price <= curr_btc['lower_band']: score += self.weights['bb_lower']
                # 4H Trendi punktid
                if curr_4h['close'] > curr_4h['ema200']: score += self.weights['trend_4h']
                # MACD punktid
                if curr_btc['macd'] > curr_btc['signal']: score += self.weights['macd']
                # Order Flow punktid
                if pressure > 1.2: score += self.weights['order_flow']
                # F&G punktid (Fear on hea ostmiseks)
                if fng < 30: score += self.weights['fng']
                
                # ETH Korrelatsiooni kontroll
                btc_move = (curr_btc['close'] - curr_btc['open']) / curr_btc['open']
                eth_move = (curr_eth['close'] - curr_eth['open']) / curr_eth['open']
                corr_ok = (btc_move > 0 and eth_move > 0) or (btc_move < 0 and eth_move < 0)
                if corr_ok: score += self.weights['eth_correlation']

                # USALDUSPROTSENT
                conf = (score / sum(self.weights.values())) * 100
                if curr_btc['volatility'] < 0.0008: conf *= 0.7 # Vähendame usaldust kui turg "elab"

                # 3. TEHINGUTE OTSUS
                pf = self.supabase.table("portfolio").select("*").eq("id", 1).execute().data[0]
                usdt, btc_bal = float(pf['usdt_balance']), float(pf['btc_balance'])
                action = "HOLD"
                reason = "Ootel"

                current_time = time.time()
                can_trade = (current_time - self.last_trade_time) > self.cooldown

                # OSTULOOGIKA (Bottom finder + Panic protection)
                if usdt > 10 and not curr_btc['is_panic'] and conf >= 72 and can_trade:
                    if price > prev_btc['low']: # Põrke kinnitus
                        action = "BUY"
                        self.supabase.table("portfolio").update({"usdt_balance": 0, "btc_balance": usdt/price}).eq("id", 1).execute()
                        self.last_trade_time = current_time
                        reason = "Tugev signaal + Põrge"

                # MÜÜGILOOGIKA
                elif btc_bal > 0:
                    if curr_btc['rsi'] > 70 or pressure < 0.7 or fng > 80:
                        action = "SELL"
                        self.supabase.table("portfolio").update({"usdt_balance": btc_bal*price, "btc_balance": 0}).eq("id", 1).execute()
                        self.last_trade_time = current_time
                        reason = "Kasumi võtmine"

                # 4. SALVESTAMINE
                total_val = usdt + (btc_bal * price)
                self.supabase.table("portfolio").update({"total_value_usdt": total_val}).eq("id", 1).execute()
                
                summary = f"{reason} | Conf: {round(conf,1)}% | Press: {round(pressure,2)} | F&G: {fng} | Panic: {curr_btc['is_panic']}"
                self.supabase.table("trade_logs").insert({
                    "symbol": self.symbol, "price": price, "rsi": curr_btc['rsi'], 
                    "action": action, "analysis_summary": summary
                }).execute()

                logger.info(f"STATUS: {price} | Conf: {round(conf,1)}% | Pressure: {round(pressure,2)} | {action}")

                # Dünaamiline uni
                sleep_time = 30 if curr_btc['volatility'] > 0.002 else 60
                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Viga: {e}")
                time.sleep(60)

if __name__ == "__main__":
    UltimateGodBot().start()