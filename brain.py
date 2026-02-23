import os
import time
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging
from cleaner import run_smart_cleanup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# AJASTUSED
DASHBOARD_UPDATE_INTERVAL = 5
AI_TRAIN_INTERVAL = 1800
OPTIMIZE_INTERVAL = 86400 # Optimeerime seadeid kord päevas

def optimize_strategy():
    logger.info("🔧 Alustan strateegia iseseisvat optimeerimist...")
    try:
        # Võtame viimased 100 tehingut
        res = supabase.table("trade_logs").select("*").not_.is_("pnl", "null").limit(100).execute()
        if not res.data or len(res.data) < 5:
            logger.info("Liiga vähe tehinguid optimeerimiseks.")
            return

        df = pd.DataFrame(res.data)
        avg_pnl = df['pnl'].mean()
        
        # LIHTNE ISEÕPPIMISE LOOGIKA:
        # Kui keskmine PnL on negatiivne, muudame boti ettevaatlikumaks
        new_sl = -2.0
        new_tp = 3.0
        new_conf = 0.6

        if avg_pnl < 0:
            new_sl = -1.5 # Kitsam stop-loss, et säästa raha
            new_conf = 0.7 # Nõuame AI-lt suuremat kindlustunnet
            logger.info("📉 Turg on raske. Muudan boti ettevaatlikumaks.")
        elif avg_pnl > 0.5:
            new_sl = -2.5 # Lubame rohkem "hingamisruumi"
            new_tp = 4.0  # Sihtime suuremat kasumit
            logger.info("🚀 Botil läheb hästi! Tõstan julgust.")

        # Uuendame seadeid andmebaasis
        supabase.table("bot_settings").update({
            "stop_loss": new_sl,
            "take_profit": new_tp,
            "min_ai_confidence": new_conf,
            "last_optimized": "now()"
        }).eq("id", 1).execute()
        
        logger.info(f"✅ Seaded uuendatud: SL:{new_sl}, TP:{new_tp}, Conf:{new_conf}")
    except Exception as e:
        logger.error(f"Viga optimeerimisel: {e}")

def run_brain_cycle(last_train_time):
    # (Siia jääb sama kood, mis varem Dashboardi ja AI treenimiseks)
    # ... (vaata eelmist täielikku brain.py koodi)
    return last_train_time

if __name__ == "__main__":
    last_train_time = 0 
    last_cleanup_time = time.time()
    last_optimize_time = 0
    
    while True:
        current_time = time.time()
        last_train_time = run_brain_cycle(last_train_time)
        
        # 1. Automaatne puhastus
        if current_time - last_cleanup_time >= 86400:
            run_smart_cleanup()
            last_cleanup_time = current_time
            
        # 2. Automaatne strateegia optimeerimine
        if current_time - last_optimize_time >= OPTIMIZE_INTERVAL:
            optimize_strategy()
            last_optimize_time = current_time
            
        time.sleep(DASHBOARD_UPDATE_INTERVAL)