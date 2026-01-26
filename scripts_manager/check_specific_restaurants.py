#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour vérifier des restaurants spécifiques
"""

import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'butter_web_interface.settings')
import django
django.setup()

from scripts_manager.firebase_utils import get_firebase_env_from_session, get_service_account_path
import firebase_admin
from firebase_admin import credentials, firestore

# Liste des restaurants à vérifier (par tag ou ID)
RESTAURANTS_TO_CHECK = ['ILC', 'BAIG', 'BOM', 'BOUC', 'BRA', 'CHEG', 'CHEJU', 'COLL', 'DAIM', 'DRO', 'FEL', 'HAL', 'KOM', 'LAP', 'RED', 'TEMP']

def init_firestore_db():
    try:
        from scripts_manager.firebase_utils import get_service_account_path
        sa = get_service_account_path(None)
    except ImportError:
        from scripts_manager.config import SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD
        env = os.getenv('FIREBASE_ENV', 'prod').lower()
        if env == 'dev':
            sa = SERVICE_ACCOUNT_PATH_DEV
        else:
            sa = SERVICE_ACCOUNT_PATH_PROD
    
    if not os.path.exists(sa):
        raise FileNotFoundError(f"Service account introuvable: {sa}")
    
    cred = credentials.Certificate(sa)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()

def main():
    env = get_firebase_env_from_session(None)
    print(f"🌍 Environnement: {env.upper()}\n")
    
    db = init_firestore_db()
    
    # Chercher par tag ET par ID
    found = []
    not_found = []
    
    for identifier in RESTAURANTS_TO_CHECK:
        # Chercher par ID
        doc = db.collection('restaurants').document(identifier).get()
        
        if not doc.exists:
            # Chercher par tag
            query = db.collection('restaurants').where('tag', '==', identifier).limit(1).stream()
            docs = list(query)
            if docs:
                doc = docs[0]
            else:
                not_found.append(identifier)
                continue
        
        data = doc.to_dict()
        restaurant_id = doc.id
        
        preferences = data.get('preferences', [])
        preferences_tag = data.get('preferences_tag', [])
        lieux = data.get('lieux', [])
        lieu_tag = data.get('lieu_tag', [])
        
        has_in_pref = 'Salle privatisable' in preferences or 'Salle privatisable' in preferences_tag
        has_in_lieu = 'Salle privatisable' in lieux or 'Salle privatisable' in lieu_tag
        
        found.append({
            'id': restaurant_id,
            'tag': data.get('tag', 'N/A'),
            'name': data.get('name', 'N/A'),
            'has_in_pref': has_in_pref,
            'has_in_lieu': has_in_lieu,
            'preferences': preferences,
            'preferences_tag': preferences_tag,
            'lieux': lieux,
            'lieu_tag': lieu_tag,
        })
    
    print("=" * 80)
    print("RÉSULTATS:")
    print("=" * 80)
    
    for r in found:
        if r['has_in_pref'] and not r['has_in_lieu']:
            status = "❌ INCORRECT"
        elif r['has_in_lieu'] and not r['has_in_pref']:
            status = "✅ CORRECT"
        elif r['has_in_pref'] and r['has_in_lieu']:
            status = "⚠️  DANS LES DEUX"
        else:
            status = "ℹ️  PAS DE 'Salle privatisable'"
        
        print(f"\n{status} - {r['id']} / {r['tag']} ({r['name']})")
        print(f"  preferences: {r['preferences']}")
        print(f"  preferences_tag: {r['preferences_tag']}")
        print(f"  lieux: {r['lieux']}")
        print(f"  lieu_tag: {r['lieu_tag']}")
    
    if not_found:
        print(f"\n⚠️  Restaurants non trouvés: {not_found}")

if __name__ == '__main__':
    main()
