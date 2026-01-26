#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour déplacer "Salle privatisable" de preferences vers lieux dans Firestore
pour les 16 restaurants concernés.
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

# Liste des 16 restaurants à corriger
RESTAURANTS_TO_FIX = [
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
        sa = get_service_account_path(None)  # Pas de request, utiliser env par défaut
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

def fix_restaurant(db, restaurant_id):
    """Corrige un restaurant en déplaçant 'Salle privatisable' de preferences vers lieux"""
    restaurant_ref = db.collection('restaurants').document(restaurant_id)
    restaurant_doc = restaurant_ref.get()
    
    if not restaurant_doc.exists:
        print(f"  ❌ Restaurant {restaurant_id} introuvable")
        return False
    
    data = restaurant_doc.to_dict()
    
    # Vérifier si "Salle privatisable" est dans preferences
    preferences = data.get('preferences', [])
    preferences_tag = data.get('preferences_tag', [])
    
    has_salle_in_pref = 'Salle privatisable' in preferences or 'Salle privatisable' in preferences_tag
    
    if not has_salle_in_pref:
        print(f"  ⚠️  Restaurant {restaurant_id}: 'Salle privatisable' pas trouvé dans preferences")
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
    
    print(f"  ✅ Restaurant {restaurant_id} corrigé:")
    print(f"     - Retiré de preferences: {preferences} → {new_preferences}")
    print(f"     - Ajouté à lieux: {lieux} → {new_lieux}")
    
    return True

def main():
    """Fonction principale"""
    import sys
    
    print("=" * 80)
    print("CORRECTION DE 'Salle privatisable' DANS FIRESTORE")
    print("=" * 80)
    
    # Vérifier l'environnement
    env = get_firebase_env_from_session(None)
    print(f"\n🌍 Environnement: {env.upper()}")
    
    # Vérifier si --yes est passé en argument
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv
    
    if env != 'dev' and not auto_confirm:
        try:
            response = input(f"\n⚠️  Vous êtes en mode {env.upper()}. Continuer quand même ? (oui/non): ")
            if response.lower() != 'oui':
                print("❌ Opération annulée")
                return
        except EOFError:
            print("\n⚠️  Mode non-interactif détecté. Utilisez --yes pour confirmer automatiquement.")
            print("❌ Opération annulée")
            return
    
    # Initialiser Firestore
    try:
        db = init_firestore_db()
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation de Firestore: {e}")
        return
    
    print(f"\n📋 {len(RESTAURANTS_TO_FIX)} restaurants à corriger\n")
    
    # Corriger chaque restaurant
    success_count = 0
    error_count = 0
    
    for restaurant_id in RESTAURANTS_TO_FIX:
        print(f"🔄 Traitement de {restaurant_id}...")
        try:
            if fix_restaurant(db, restaurant_id):
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            print(f"  ❌ Erreur: {e}")
            error_count += 1
    
    # Résumé
    print("\n" + "=" * 80)
    print("RÉSUMÉ:")
    print("=" * 80)
    print(f"✅ Restaurants corrigés: {success_count}")
    print(f"❌ Erreurs: {error_count}")
    print(f"📊 Total: {len(RESTAURANTS_TO_FIX)}")
    print("\n✅ Correction terminée !")

if __name__ == '__main__':
    main()
