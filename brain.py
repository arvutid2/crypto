import os
import time
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging
from cleaner import run_smart_cleanup  # Impordime puhastusfunktsiooni

# 1. SEADISTAMINE JA LOGID
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# 2. AJASTUSE SEADED (Sekundites)
DASHBOARD_UPDATE_INTERVAL = 5    # Dashboard uueneb iga 5 sekundi järel
AI_TRAIN_INTERVAL = 1800        # AI treenib iga 30 minuti järel
CLEANUP_INTERVAL = 86400        # Puhastus jookseb kord 24 tunni jooksul

def run_brain_cycle(last_train_time):
    current_time = time.time()
    
    # Tõmbame viimased andmed analüüsiks
    try:
        res = supabase.table("trade_logs").select("*").order("created_at", desc=True).limit(500).execute()
        if not res.data or len(res.data) < 20:
            return last_train_time
        
        df = pd.DataFrame(res.data)
    except Exception as e:
        logger.error(f"Viga andmete pärimisel: {e}")
        return last_train_time

    # --- OSA A: DASHBOARDI UUENDAMINE ---
    try:
        # Arvutame PnL summa trade_logs tabelist
        pnl_sum = df['pnl'].dropna().sum()
        
        # Sinu algne baas-saldo (pildilt nähtud summa)
        base_balance = 9979.54
        new_total = base_balance * (1 + (pnl_sum / 100))
        
        portfolio_update = {
            "total_value_usdt": float(new_total),
            "usdt_balance": float(new_total),
            "last_updated": "now()"
        }
        
        # Uuendame 'portfolio' tabelis rida id=1
        supabase.table("portfolio").update(portfolio_update).eq("id", 1).execute()
        logger.info(f"📊 Dashboard: {new_total:.2f} USDT | PnL: {pnl_sum:.2f}%")
    except Exception as e:
        logger.error(f"Viga Dashboardi uuendamisel: {e}")

    # --- OSA B: AI TREENIMINE ---
    if current_time - last_train_time >= AI_TRAIN_INTERVAL:
        logger.info("🧠 Alustan AI treenimist (F&G, Pressure, RSI)...")
        try:
            # Märgistame sihtmärgi: kas hind tõuseb 3 sammu pärast
            df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
            
            features = ['price', 'rsi', 'market_pressure', 'fear_greed_index']
            
            # Puhastame andmed treeninguks
            X = df[features].fillna(0)
            y = df['target'].fillna(0)

            model = RandomForestClassifier(n_estimators=100)
            model.fit(X, y)
            joblib.dump(model, 'trading_brain.pkl')
            
            logger.info("✅ AI Mudel on värskendatud!")
            return current_time
        except Exception as e:
            logger.error(f"Viga AI treenimisel: {e}")
            return last_train_time
            
    return last_train_time

if __name__ == "__main__":
    logger.info("🔥 BRAIN TEENUS ON ONLINE")
    logger.info(f"Sünkroniseerimine: Dashboard {DASHBOARD_UPDATE_INTERVAL}s | AI {AI_TRAIN_INTERVAL/60}min | Cleaner 24h")
    
    last_train_time = 0 
    last_cleanup_time = time.time() # Alustame loendust praegusest hetkest
    
    while True:
        try:
            # 1. Dashboard ja AI tsükkel
            last_train_time = run_brain_cycle(last_train_time)
            
            # 2. Automaatne andmete puhastus (Cleaner)
            current_time = time.time()
            if current_time - last_cleanup_time >= CLEANUP_INTERVAL:
                run_smart_cleanup()
                last_cleanup_time = current_time
                
        except Exception as e:
            logger.error(f"Viga põhitsüklis: {e}")
            
        time.sleep(DASHBOARD_UPDATE_INTERVAL)