#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json
import firebase_admin
from firebase_admin import credentials, firestore

SERVICE_ACCOUNT = "serviceAccountKey.json"  # ← adapte
COLLECTION = "restaurants"
OUT_JSON = "export_restaurants.ndjson"  # NDJSON pour fichiers volumineux

def main():
    try:
        print("🔐 Initialisation de Firebase...")
        cred = credentials.Certificate(SERVICE_ACCOUNT)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Connexion Firebase établie")

        print(f"📊 Récupération des documents de la collection '{COLLECTION}'...")
        docs = db.collection(COLLECTION).stream()
        
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            count = 0
            for doc in docs:
                row = {"id": doc.id, **(doc.to_dict() or {})}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
                if count % 100 == 0:
                    print(f"  📝 {count} documents traités...")
        
        print(f"✅ Exporté {count} documents vers {OUT_JSON}")
        
    except FileNotFoundError:
        print(f"❌ Erreur: Fichier {SERVICE_ACCOUNT} non trouvé")
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    main()
