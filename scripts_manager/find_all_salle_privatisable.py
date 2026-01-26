#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour trouver TOUS les restaurants avec "Salle privatisable" dans preferences
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

def main():
    """Fonction principale"""
    print("=" * 80)
    print("RECHERCHE DE TOUS LES RESTAURANTS AVEC 'Salle privatisable'")
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
    
    # Récupérer tous les restaurants
    print("🔍 Recherche de tous les restaurants...")
    restaurants_ref = db.collection('restaurants')
    all_restaurants = restaurants_ref.stream()
    
    restaurants_with_salle_in_pref = []
    restaurants_with_salle_in_lieu = []
    restaurants_with_salle_both = []
    
    total = 0
    for doc in all_restaurants:
        total += 1
        data = doc.to_dict()
        restaurant_id = doc.id
        
        preferences = data.get('preferences', [])
        preferences_tag = data.get('preferences_tag', [])
        lieux = data.get('lieux', [])
        lieu_tag = data.get('lieu_tag', [])
        location_type = data.get('location_type', [])
        
        has_in_pref = 'Salle privatisable' in preferences or 'Salle privatisable' in preferences_tag
        has_in_lieu = 'Salle privatisable' in lieux or 'Salle privatisable' in lieu_tag or 'Salle privatisable' in location_type
        
        restaurant_info = {
            'id': restaurant_id,
            'name': data.get('name', 'N/A'),
            'tag': data.get('tag', 'N/A'),
            'preferences': preferences,
            'preferences_tag': preferences_tag,
            'lieux': lieux,
            'lieu_tag': lieu_tag,
            'location_type': location_type,
        }
        
        if has_in_pref and has_in_lieu:
            restaurants_with_salle_both.append(restaurant_info)
        elif has_in_pref:
            restaurants_with_salle_in_pref.append(restaurant_info)
        elif has_in_lieu:
            restaurants_with_salle_in_lieu.append(restaurant_info)
    
    # Afficher les résultats
    print(f"\n📊 Total restaurants analysés: {total}")
    print("\n" + "=" * 80)
    print("RÉSULTATS:")
    print("=" * 80)
    
    print(f"\n❌ Restaurants avec 'Salle privatisable' dans PREFERENCES uniquement ({len(restaurants_with_salle_in_pref)}):")
    for r in restaurants_with_salle_in_pref:
        print(f"   - ID: {r['id']} / Tag: {r['tag']} / Nom: {r['name']}")
        print(f"     preferences: {r['preferences']}")
        print(f"     preferences_tag: {r['preferences_tag']}")
        print(f"     lieux: {r['lieux']}")
        print(f"     lieu_tag: {r['lieu_tag']}")
        print()
    
    print(f"\n✅ Restaurants avec 'Salle privatisable' dans LIEUX uniquement ({len(restaurants_with_salle_in_lieu)}):")
    for r in restaurants_with_salle_in_lieu:
        print(f"   - ID: {r['id']} / Tag: {r['tag']} / Nom: {r['name']}")
        print(f"     preferences: {r['preferences']}")
        print(f"     lieux: {r['lieux']}")
        print(f"     lieu_tag: {r['lieu_tag']}")
        print()
    
    print(f"\n⚠️  Restaurants avec 'Salle privatisable' dans LES DEUX ({len(restaurants_with_salle_both)}):")
    for r in restaurants_with_salle_both:
        print(f"   - ID: {r['id']} / Tag: {r['tag']} / Nom: {r['name']}")
        print(f"     preferences: {r['preferences']}")
        print(f"     lieux: {r['lieux']}")
        print()
    
    # Résumé
    print("\n" + "=" * 80)
    print("RÉSUMÉ:")
    print("=" * 80)
    print(f"❌ À corriger (dans preferences uniquement): {len(restaurants_with_salle_in_pref)}")
    print(f"✅ Corrects (dans lieux uniquement): {len(restaurants_with_salle_in_lieu)}")
    print(f"⚠️  Dans les deux: {len(restaurants_with_salle_both)}")
    
    # Retourner la liste des IDs à corriger
    if restaurants_with_salle_in_pref or restaurants_with_salle_both:
        ids_to_fix = [r['id'] for r in restaurants_with_salle_in_pref] + [r['id'] for r in restaurants_with_salle_both]
        print(f"\n📋 IDs à corriger: {ids_to_fix}")

if __name__ == '__main__':
    main()
