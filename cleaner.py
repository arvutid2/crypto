import os
import logging
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

# Logimine
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [cleaner] %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def run_smart_cleanup():
    logger.info("🧹 Alustan andmebaasi tarka puhastust...")
    
    try:
        # 1. Arvutame kuupäeva (3 päeva tagasi)
        cutoff_date = (datetime.now() - timedelta(days=3)).isoformat()
        
        # 2. KUSTUTAME: Ainult 'HOLD' read, mis on vanemad kui 3 päeva
        # NB! 'BUY' ja 'SELL' read jäävad puutumata, sest neil puudub tingimus 'HOLD'
        response = supabase.table("trade_logs") \
            .delete() \
            .eq("action", "HOLD") \
            .lt("created_at", cutoff_date) \
            .execute()
        
        # Loendame, kui palju ridu eemaldati (Supabase tagastab andmed .data all)
        deleted_count = len(response.data) if response.data else 0
        
        logger.info(f"✅ Puhastus lõpetatud! Eemaldati {deleted_count} vana 'HOLD' rida.")
        logger.info("📌 Kõik tehingud (BUY/SELL) ja viimase 3 päeva ajalugu on alles.")

    except Exception as e:
        logger.error(f"❌ Viga puhastamise käigus: {e}")

if __name__ == "__main__":
    # Saame lisada siia ka tsükli, et ta puhastaks nt kord ööpäevas
    run_smart_cleanup()