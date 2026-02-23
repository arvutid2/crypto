import os
import time
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
# use a more capable learner, falls back to RF if xgboost is missing
try:
    from xgboost import XGBClassifier
except ImportError:
    from sklearn.ensemble import RandomForestClassifier as XGBClassifier

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

# VasXX sündmuste või versiooni info
MODEL_FILENAME = 'trading_brain.pkl'  # võib hiljem versioonideks laiendada

def train_ai_model():
    logger.info("🧠 Kontrollin andmeid uue mudeli jaoks...")
    try:
        # Võtame kõik read, kus uued indikaatorid on täidetud
        res = supabase.table("trade_logs").select("*").not_.is_("macd", "null").order("created_at", desc=True).limit(2000).execute()
        
        if not res.data or len(res.data) < 50:
            logger.info(f"Ootel: Vaja on vähemalt 50 uute andmetega rida (hetkel on {len(res.data) if res.data else 0}).")
            return False

        df = pd.DataFrame(res.data)
        # Target: kas hind tõusis 3 min pärast?
        df['target'] = (df['price'].shift(-3) > df['price']).astype(int)
        
        # uued tunnused
        base_features = [
            'price', 'rsi', 'macd', 'macd_signal',
            'bb_upper', 'bb_lower', 'atr', 'ema200',
            'market_pressure', 'fear_greed_index',
            'volume', 'vwap', 'stoch_k', 'stoch_d'
        ]
        # filtreerime välja need tunnused, mida andmetes ei ole
        features = [f for f in base_features if f in df.columns]
        missing = set(base_features) - set(features)
        if missing:
            logger.info(f"Andmetest puuduvad tunnused: {sorted(missing)}. Treenime {len(features)} tunnusega.")
        if not features:
            logger.error("Treenimisprobleem: ei leitud ühiseid tunnuseid.")
            return False
        
        train_df = df.dropna(subset=features + ['target'])
        
        if len(train_df) < 15:
            logger.info("Pärast tühjade ridade eemaldamist jäi liiga vähe andmeid.")
            return False

        X = train_df[features]
        y = train_df['target']

        # jagame andmed treeningu- ja valideerimisosaks, et kiire ülevaade saada
        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

        # XGBClassifier on spetsiifiliselt ajaseeria jaoks hea; RandomForest on tagavaraks
        model = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.1, use_label_encoder=False, eval_metric='logloss')
        model.fit(X_train, y_train)

        # valideerimise täpsus
        preds = model.predict(X_val)
        acc = accuracy_score(y_val, preds)
        logger.info(f"Valideerimise täpsus: {acc:.3f} ({len(y_val)} näidet)")

        joblib.dump(model, MODEL_FILENAME)
        logger.info(f"🚀 UUS MUDEL LOODUD! Treenitud {len(X_train)} + validate {len(X_val)} rea põhjal.")
        
        # juhul kui mudel toetab osalist õppimist, jätkame järk‑järgset uuendamist
        if hasattr(model, 'partial_fit'):
            logger.info("Mudelis partiaallärmine aktiivne.")
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