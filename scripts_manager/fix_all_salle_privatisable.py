#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour corriger TOUS les restaurants avec "Salle privatisable" dans preferences
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

def fix_restaurant(db, restaurant_ref, restaurant_id, data):
    """Corrige un restaurant en déplaçant 'Salle privatisable' de preferences vers lieux"""
    preferences = data.get('preferences', [])
    preferences_tag = data.get('preferences_tag', [])
    
    has_salle_in_pref = 'Salle privatisable' in preferences or 'Salle privatisable' in preferences_tag
    
    if not has_salle_in_pref:
        return False
    
    # Récupérer les lieux actuels
    lieux = data.get('lieux', [])
    lieu_tag = data.get('lieu_tag', [])
    location_type = data.get('location_type', [])
    
    # Retirer "Salle privatisable" des préférences
    new_preferences = [p for p in preferences if p != 'Salle privatisable']
    new_preferences_tag = [p for p in preferences_tag if p != 'Salle privatisable']
    
    # Ajouter "Salle privatisable" aux lieux (s'il n'y est pas déjà)
    new_lieux = list(lieux) if isinstance(lieux, list) else []
    if 'Salle privatisable' not in new_lieux:
        new_lieux.append('Salle privatisable')
    
    new_lieu_tag = list(lieu_tag) if isinstance(lieu_tag, list) else []
    if 'Salle privatisable' not in new_lieu_tag:
        new_lieu_tag.append('Salle privatisable')
    
    new_location_type = list(location_type) if isinstance(location_type, list) else []
    if 'Salle privatisable' not in new_location_type:
        new_location_type.append('Salle privatisable')
    
    # Préparer les mises à jour
    updates = {
        'preferences': new_preferences,
        'preferences_tag': new_preferences_tag,
        'lieux': new_lieux,
        'lieu_tag': new_lieu_tag,
        'location_type': new_location_type,
    }
    
    # Mettre à jour
    restaurant_ref.update(updates)
    
    return True

def main():
    """Fonction principale"""
    import sys
    
    print("=" * 80)
    print("CORRECTION AUTOMATIQUE DE 'Salle privatisable' DANS FIRESTORE")
    print("=" * 80)
    
    # Vérifier l'environnement - UNIQUEMENT DEV
    env = get_firebase_env_from_session(None)
    print(f"\n🌍 Environnement: {env.upper()}")
    
    # IMPORTANT: Ce script fonctionne UNIQUEMENT en mode DEV
    if env != 'dev':
        print(f"\n❌ ERREUR: Ce script fonctionne UNIQUEMENT en mode DÉVELOPPEMENT (DEV).")
        print(f"   Environnement actuel: {env.upper()}")
        print(f"   Pour utiliser DEV, définissez: export FIREBASE_ENV=dev")
        print("❌ Opération annulée")
        return
    
    # Initialiser Firestore
    try:
        db = init_firestore_db()
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de Firestore: {e}")
        return
    
    # Récupérer tous les restaurants
    print("\n🔍 Recherche de tous les restaurants avec 'Salle privatisable' dans preferences...")
    restaurants_ref = db.collection('restaurants')
    all_restaurants = restaurants_ref.stream()
    
    restaurants_to_fix = []
    total_checked = 0
    
    for doc in all_restaurants:
        total_checked += 1
        data = doc.to_dict()
        restaurant_id = doc.id
        
        preferences = data.get('preferences', [])
        preferences_tag = data.get('preferences_tag', [])
        
        # Vérifier aussi avec différentes variantes (minuscules, etc.)
        has_salle_in_pref = (
            'Salle privatisable' in preferences or 
            'Salle privatisable' in preferences_tag or
            any('salle privatisable' in str(p).lower() for p in preferences) or
            any('salle privatisable' in str(p).lower() for p in preferences_tag)
        )
        
        if has_salle_in_pref:
            restaurants_to_fix.append({
                'ref': doc.reference,
                'id': restaurant_id,
                'tag': data.get('tag', 'N/A'),
                'name': data.get('name', 'N/A'),
                'data': data,
            })
    
    print(f"📊 {total_checked} restaurants analysés")
    
    print(f"\n📋 {len(restaurants_to_fix)} restaurants à corriger trouvés\n")
    
    if len(restaurants_to_fix) == 0:
        print("✅ Aucun restaurant à corriger !")
        return
    
    # Afficher la liste
    print("Restaurants à corriger:")
    for r in restaurants_to_fix:
        print(f"  - {r['id']} / {r['tag']} ({r['name']})")
    
    # Corriger chaque restaurant
    success_count = 0
    error_count = 0
    
    for r in restaurants_to_fix:
        print(f"\n🔄 Traitement de {r['id']} ({r['name']})...")
        try:
            if fix_restaurant(db, r['ref'], r['id'], r['data']):
                success_count += 1
                print(f"  ✅ Corrigé")
            else:
                print(f"  ⚠️  Pas de correction nécessaire")
        except Exception as e:
            print(f"  ❌ Erreur: {e}")
            error_count += 1
    
    # Résumé
    print("\n" + "=" * 80)
    print("RÉSUMÉ:")
    print("=" * 80)
    print(f"✅ Restaurants corrigés: {success_count}")
    print(f"❌ Erreurs: {error_count}")
    print(f"📊 Total: {len(restaurants_to_fix)}")
    print("\n✅ Correction terminée !")

if __name__ == '__main__':
    main()
