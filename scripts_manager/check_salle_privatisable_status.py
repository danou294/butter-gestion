#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour vérifier l'état actuel de "Salle privatisable" dans Firestore
"""

import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports Django
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'butter_web_interface.settings')
import django
django.setup()

from scripts_manager.firebase_utils import get_firebase_env_from_session, get_service_account_path
import firebase_admin
from firebase_admin import credentials, firestore

# Liste des 16 restaurants à vérifier
RESTAURANTS_TO_CHECK = [
    'BAIG',  # La Baignoire
    'BOM',   # Bombarde restaurant
    'BOUC',  # Bouche
    'BRA',   # Brasserie Rosie
    'CHEG',  # Chez Gala
    'CHEJU', # Chez Julien
    'COLL',  # Collier de la reine
    'DAIM',  # Daimant
    'DRO',   # Drouant
    'FEL',   # Fellows
    'HAL',   # Halo
    'ILC',   # Il camino
    'KOM',   # Komatsubaki
    'LAP',   # Lapérouse
    'RED',   # Red Katz
    'TEMP',  # Temple et Chapon
]

def init_firestore_db():
    """Initialise Firestore avec l'environnement actuel"""
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
    
    print(f"🔑 Utilisation du service account: {sa}")
    cred = credentials.Certificate(sa)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()

def check_restaurant(db, restaurant_id):
    """Vérifie l'état d'un restaurant"""
    restaurant_ref = db.collection('restaurants').document(restaurant_id)
    restaurant_doc = restaurant_ref.get()
    
    if not restaurant_doc.exists:
        return None
    
    data = restaurant_doc.to_dict()
    
    preferences = data.get('preferences', [])
    preferences_tag = data.get('preferences_tag', [])
    lieux = data.get('lieux', [])
    lieu_tag = data.get('lieu_tag', [])
    location_type = data.get('location_type', [])
    
    has_in_pref = 'Salle privatisable' in preferences or 'Salle privatisable' in preferences_tag
    has_in_lieu = 'Salle privatisable' in lieux or 'Salle privatisable' in lieu_tag or 'Salle privatisable' in location_type
    
    return {
        'id': restaurant_id,
        'name': data.get('name', 'N/A'),
        'has_in_pref': has_in_pref,
        'has_in_lieu': has_in_lieu,
        'preferences': preferences,
        'preferences_tag': preferences_tag,
        'lieux': lieux,
        'lieu_tag': lieu_tag,
        'location_type': location_type,
    }

def main():
    """Fonction principale"""
    print("=" * 80)
    print("VÉRIFICATION DE 'Salle privatisable' DANS FIRESTORE")
    print("=" * 80)
    
    # Vérifier l'environnement
    env = get_firebase_env_from_session(None)
    print(f"\n🌍 Environnement: {env.upper()}\n")
    
    # Initialiser Firestore
    try:
        db = init_firestore_db()
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de Firestore: {e}")
        return
    
    # Vérifier chaque restaurant
    results = []
    for restaurant_id in RESTAURANTS_TO_CHECK:
        result = check_restaurant(db, restaurant_id)
        if result:
            results.append(result)
    
    # Afficher les résultats
    print("=" * 80)
    print("RÉSULTATS:")
    print("=" * 80)
    
    correct = []
    incorrect = []
    missing = []
    
    for r in results:
        if r['has_in_lieu'] and not r['has_in_pref']:
            correct.append(r)
            status = "✅ CORRECT"
        elif r['has_in_pref']:
            incorrect.append(r)
            status = "❌ INCORRECT (dans preferences)"
        else:
            missing.append(r)
            status = "⚠️  MANQUANT (pas dans lieux ni preferences)"
        
        print(f"\n{status} - {r['id']} ({r['name']})")
        print(f"  preferences: {r['preferences']}")
        print(f"  preferences_tag: {r['preferences_tag']}")
        print(f"  lieux: {r['lieux']}")
        print(f"  lieu_tag: {r['lieu_tag']}")
        print(f"  location_type: {r['location_type']}")
    
    # Résumé
    print("\n" + "=" * 80)
    print("RÉSUMÉ:")
    print("=" * 80)
    print(f"✅ Corrects: {len(correct)}")
    print(f"❌ Incorrects (dans preferences): {len(incorrect)}")
    print(f"⚠️  Manquants: {len(missing)}")
    print(f"📊 Total vérifiés: {len(results)}")
    
    if incorrect:
        print(f"\n❌ Restaurants à corriger ({len(incorrect)}):")
        for r in incorrect:
            print(f"   - {r['id']} ({r['name']})")

if __name__ == '__main__':
    main()
