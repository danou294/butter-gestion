#!/usr/bin/env python3
"""
Script pour vérifier les logos manquants dans le dossier Logos/
Compare les identifiants des restaurants avec les fichiers présents dans Logos/
"""

import os
import sys
import json
from google.cloud import storage
from google.oauth2 import service_account
import logging
from datetime import datetime

# Configuration du logging
def setup_logging():
    """Configure le système de logging"""
    log_dir = "../exports"
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "check_missing_logos.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def get_storage_client():
    """Initialise le client Google Cloud Storage"""
    try:
        key_path = "../../input/serviceAccountKey.json"
        
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Fichier de clé non trouvé : {key_path}")
        
        credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        
        client = storage.Client(credentials=credentials)
        return client
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation du client Storage : {e}")
        return None

def load_restaurant_ids():
    """Charge les identifiants des restaurants depuis le fichier JSON"""
    try:
        ids_file = "../exports/restaurant_ids.json"
        
        if not os.path.exists(ids_file):
            raise FileNotFoundError(f"Fichier des identifiants non trouvé : {ids_file}")
        
        with open(ids_file, 'r', encoding='utf-8') as f:
            restaurant_ids = json.load(f)
        
        return restaurant_ids
    except Exception as e:
        print(f"❌ Erreur lors du chargement des identifiants : {e}")
        return None

def check_missing_logos():
    """Vérifie les logos manquants"""
    logger = setup_logging()
    
    logger.info("🔍 Début de la vérification des logos manquants")
    
    # Chargement des identifiants des restaurants
    restaurant_ids = load_restaurant_ids()
    if not restaurant_ids:
        return
    
    logger.info(f"📊 Total restaurants dans la base : {len(restaurant_ids)}")
    
    # Initialisation du client Storage
    client = get_storage_client()
    if not client:
        return
    
    try:
        # Récupération du bucket
        bucket_name = "butter-vdef.firebasestorage.app"
        bucket = client.bucket(bucket_name)
        
        logger.info(f"🪣 Bucket utilisé : {bucket_name}")
        logger.info(f"🔗 URL complète : gs://{bucket_name}")
        
        # Liste des fichiers dans Logos/
        prefix = "Logos/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        logger.info(f"📁 Dossier : {prefix}")
        logger.info(f"📊 Total de fichiers trouvés : {len(blobs)}")
        
        # Extraction des identifiants des logos
        logo_ids = set()
        logo_files = []
        
        logger.info("🔍 Analyse des fichiers logos :")
        for i, blob in enumerate(blobs[:10]):  # Afficher les 10 premiers
            filename = blob.name.replace(prefix, "")  # Enlever le préfixe "Logos/"
            logger.info(f"   {i+1}. {filename}")
        
        if len(blobs) > 10:
            logger.info(f"   ... et {len(blobs) - 10} autres fichiers")
        
        for blob in blobs:
            filename = blob.name.replace(prefix, "")  # Enlever le préfixe "Logos/"
            
            # Vérifier si c'est un fichier PNG avec un ID
            if filename.lower().endswith('.png'):
                # Extraire l'ID (nom du fichier sans l'extension)
                logo_id = filename.replace('.png', '').replace('.PNG', '')
                logo_ids.add(logo_id)
                logo_files.append(filename)
        
        logger.info(f"🖼️  Logos trouvés : {len(logo_ids)}")
        logger.info("🔍 Premiers identifiants de logos extraits :")
        for i, logo_id in enumerate(list(logo_ids)[:10]):
            logger.info(f"   {i+1}. {logo_id}")
        
        if len(logo_ids) > 10:
            logger.info(f"   ... et {len(logo_ids) - 10} autres identifiants")
        
        # Identifier les restaurants sans logo
        missing_logos = []
        restaurants_with_logos = []
        
        for restaurant_id in restaurant_ids:
            # Chercher les logos avec le format ID1.png, ID2.png, etc.
            found_logo = False
            for logo_id in logo_ids:
                if logo_id.startswith(restaurant_id) and logo_id[len(restaurant_id):].isdigit():
                    found_logo = True
                    restaurants_with_logos.append(restaurant_id)
                    break
            
            if not found_logo:
                missing_logos.append(restaurant_id)
        
        logger.info(f"✅ Restaurants avec logo : {len(restaurants_with_logos)}")
        logger.info("🔍 Premiers restaurants avec logo :")
        for i, restaurant_id in enumerate(restaurants_with_logos[:10]):
            logger.info(f"   {i+1}. {restaurant_id}")
        
        if len(restaurants_with_logos) > 10:
            logger.info(f"   ... et {len(restaurants_with_logos) - 10} autres")
        
        logger.info(f"❌ Restaurants sans logo : {len(missing_logos)}")
        
        # Affichage des premiers restaurants sans logo
        if missing_logos:
            logger.info("🔍 Premiers restaurants sans logo :")
            for i, restaurant_id in enumerate(missing_logos[:20]):
                logger.info(f"   {i+1}. {restaurant_id}")
            
            if len(missing_logos) > 20:
                logger.info(f"   ... et {len(missing_logos) - 20} autres")
        
        # Sauvegarde des résultats
        missing_logos_file = "../exports/missing_logos.txt"
        with open(missing_logos_file, 'w', encoding='utf-8') as f:
            f.write("RESTAURANTS SANS LOGO\n")
            f.write("="*50 + "\n\n")
            f.write(f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Dossier : {prefix}\n")
            f.write(f"Total restaurants : {len(restaurant_ids)}\n")
            f.write(f"Logos trouvés : {len(logo_ids)}\n")
            f.write(f"Restaurants sans logo : {len(missing_logos)}\n\n")
            
            f.write("LISTE DES RESTAURANTS SANS LOGO :\n")
            f.write("-" * 40 + "\n")
            for restaurant_id in missing_logos:
                f.write(f"{restaurant_id}\n")
        
        # Sauvegarde en JSON
        missing_logos_json_file = "../exports/missing_logos.json"
        with open(missing_logos_json_file, 'w', encoding='utf-8') as f:
            json.dump(missing_logos, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Liste des logos manquants sauvegardée dans : {missing_logos_file}")
        logger.info(f"💾 Liste JSON sauvegardée dans : {missing_logos_json_file}")
        
        # Résumé
        logger.info("\n" + "="*60)
        logger.info("📋 RÉSUMÉ DE LA VÉRIFICATION")
        logger.info("="*60)
        logger.info(f"   • Total restaurants : {len(restaurant_ids)}")
        logger.info(f"   • Logos trouvés : {len(logo_ids)}")
        logger.info(f"   • Restaurants avec logo : {len(restaurants_with_logos)}")
        logger.info(f"   • Restaurants sans logo : {len(missing_logos)}")
        logger.info(f"   • Pourcentage avec logo : {(len(restaurants_with_logos) / len(restaurant_ids)) * 100:.1f}%")
        logger.info("✅ VÉRIFICATION TERMINÉE")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification : {e}")
        raise

if __name__ == "__main__":
    check_missing_logos()
