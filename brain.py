import os
import time
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from supabase import create_client
from dotenv import load_dotenv
import logging

# LOGIMISE SEADISTUS - Peab olema faili alguses!
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [brain] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

try:
    supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
    logger.info("✅ Supabase ühendus loodud.")
except Exception as e:
    logger.error(f"❌ Supabase ühenduse viga: {e}")

DASHBOARD_INTERVAL = 10
TRAIN_INTERVAL = 600 # Treenime tihedamini (iga 10 min), et uued andmed kiirelt sisse saaks

def train_ai_model():
    logger.info("🧠 Kontrollin andmeid uue mudeli jaoks...")
    try:
        # Võtame kõik read, kus uued indikaatorid on täidetud
        res = supabase.table("trade_logs").select("*").not_.is_("macd", "null").order("created_at", desc=True).limit(1000).execute()
        
        if not res.data or len(res.data) < 20:
            logger.info(f"Ootel: Vaja on vähemalt 20 uute andmetega rida (hetkel on {len(res.data) if res.data else 0}).")
            return False

        df = pd.DataFrame(res.data)
        # Target: kas hind tõusis 3 min pärast?
        df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
        
        features = [
            'price', 'rsi', 'macd', 'macd_signal', 
            'bb_upper', 'bb_lower', 'atr', 'ema200',
            'market_pressure', 'fear_greed_index'
        ]
        
        train_df = df.dropna(subset=features + ['target'])
        
        if len(train_df) < 15:
            logger.info("Pärast tühjade ridade eemaldamist jäi liiga vähe andmeid.")
            return False

        X = train_df[features]
        y = train_df['target']

        model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        model.fit(X, y)
        
        joblib.dump(model, 'trading_brain.pkl')
        logger.info(f"🚀 UUS MUDEL LOODUD! Treenitud {len(X)} rea põhjal.")
        return True
    except Exception as e:
        logger.error(f"Viga treenimisel: {e}")
        return False

if __name__ == "__main__":
    logger.info("🚀 Brain.py on käivitatud ja ootab andmeid...")
    
    last_train_time = 0
    
    while True:
        try:
            current_time = time.time()
            
            # Treenimise tsükkel
            if current_time - last_train_time >= TRAIN_INTERVAL:
                success = train_ai_model()
                last_train_time = current_time
            
            # Siia võid lisada ka oma vana optimize_strategy() väljakutse
            
            time.sleep(DASHBOARD_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("Peatamine...")
            break
        except Exception as e:
            logger.error(f"Viga põhitsüklis: {e}")
            time.sleep(10)