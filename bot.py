import os
import time
import requests
import yfinance as yf
import pandas_ta as ta
from supabase import create_client
from dotenv import load_dotenv

# Laeme seaded .env failist
load_dotenv()

# Supabase seaded
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Uudiste API (valikuline - kui sul on CryptoPanic võti, pane see .env faili)
CRYPTO_PANIC_KEY = os.getenv("CRYPTO_PANIC_KEY")

def get_sentiment():
    """Küsime viimaseid uudiseid ja hindame meeleolu"""
    if not CRYPTO_PANIC_KEY:
        return 0 # Kui võtit pole, tagastame neutraalse tulemuse
    
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_PANIC_KEY}&currencies=BTC"
        r = requests.get(url).json()
        pos = sum([post.get('votes', {}).get('positive', 0) for post in r['results'][:10]])
        neg = sum([post.get('votes', {}).get('negative', 0) for post in r['results'][:10]])
        
        total = pos + neg
        return (pos - neg) / total if total > 0 else 0
    except:
        return 0

def run_bot():
    print("🚀 Bot on käivitatud ja otsib signaale...")
    
    while True:
        try:
            # 1. Hinnainfo pärimine
            ticker = yf.Ticker("BTC-USD")
            data = ticker.history(period="1d", interval="15m")
            current_price = data['Close'].iloc[-1]
            
            # 2. Tehniline analüüs (RSI)
            rsi = ta.rsi(data['Close'], length=14).iloc[-1]
            
            # 3. Uudiste analüüs
            sentiment = get_sentiment()
            
            # 4. OTSUSE LOOGIKA (Siin on boti "tarkus")
            # Kombineerime RSI ja uudised
            action = "HOLD"
            analysis = f"RSI: {round(rsi, 1)}, Sentiment: {round(sentiment, 2)}. "

            if rsi < 35 and sentiment > 0:
                action = "BUY"
                analysis += "Turg on ülemüüdud ja uudised on positiivsed. Hea aeg osta!"
            elif rsi > 65 and sentiment < 0:
                action = "SELL"
                analysis += "Turg on üleostetud ja uudised on negatiivsed. Targem on müüa."
            else:
                analysis += "Ootame selgemat signaali."

            # 5. ANDMETE SAATMINE SUPABASE'I (Sinu Lovable dashboardile)
            entry = {
                "symbol": "BTC/USDT",
                "price": float(current_price),
                "rsi": float(rsi),
                "action": action,
                "analysis_summary": analysis
            }
            
            supabase.table("trade_logs").insert(entry).execute()
            print(f"✅ Salvestatud: BTC @ {round(current_price, 2)} | Otsus: {action}")
            
            # Ootame 15 minutit enne järgmist kontrolli
            time.sleep(60)
            
        except Exception as e:
            print(f"❌ Viga tekkis: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()