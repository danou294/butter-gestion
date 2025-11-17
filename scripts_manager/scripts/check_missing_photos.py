#!/usr/bin/env python3
"""
Script pour vérifier les photos manquantes dans le dossier Photos restaurants/
Génère un fichier Excel avec les détails des photos manquantes
"""

import os
import sys
import json
import pandas as pd
from google.cloud import storage
from google.oauth2 import service_account
import logging
from datetime import datetime

# Configuration du logging
def setup_logging():
    """Configure le système de logging"""
    log_dir = "exports"
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "check_missing_photos.log")
    
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
        key_path = "input/serviceAccountKey.json"
        
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
        ids_file = "exports/restaurant_ids.json"
        
        if not os.path.exists(ids_file):
            raise FileNotFoundError(f"Fichier des identifiants non trouvé : {ids_file}")
        
        with open(ids_file, 'r', encoding='utf-8') as f:
            restaurant_ids = json.load(f)
        
        return restaurant_ids
    except Exception as e:
        print(f"❌ Erreur lors du chargement des identifiants : {e}")
        return None

def check_missing_photos():
    """Vérifie les photos manquantes et génère un Excel"""
    logger = setup_logging()
    
    logger.info("🔍 Début de la vérification des photos manquantes")
    
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
        
        # Liste des fichiers dans Photos restaurants/
        prefix = "Photos restaurants/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        logger.info(f"📁 Dossier : {prefix}")
        logger.info(f"📊 Total de fichiers trouvés : {len(blobs)}")
        
        # Extraction des photos par restaurant
        restaurant_photos = {}
        
        for blob in blobs:
            filename = blob.name.replace(prefix, "")  # Enlever le préfixe "Photos restaurants/"
            
            # Vérifier si c'est un fichier WebP
            if filename.lower().endswith('.webp'):
                # Extraire l'ID du restaurant et le numéro de photo
                # Format attendu : ABR1.webp, ABR2.webp, etc.
                base_name = filename.replace('.webp', '').replace('.WEBP', '')
                
                # Trouver le restaurant (partie avant le chiffre)
                restaurant_id = None
                photo_number = None
                
                for i in range(len(base_name), 0, -1):
                    if base_name[:i] in restaurant_ids:
                        restaurant_id = base_name[:i]
                        photo_number = base_name[i:]
                        break
                
                if restaurant_id and photo_number.isdigit():
                    if restaurant_id not in restaurant_photos:
                        restaurant_photos[restaurant_id] = set()
                    restaurant_photos[restaurant_id].add(int(photo_number))
        
        logger.info(f"🖼️  Restaurants avec photos : {len(restaurant_photos)}")
        
        # Vérification des photos manquantes
        missing_photos_data = []
        
        for restaurant_id in restaurant_ids:
            if restaurant_id in restaurant_photos:
                existing_photos = restaurant_photos[restaurant_id]
                max_photo = max(existing_photos) if existing_photos else 0
                
                # Vérifier les photos manquantes (2 à max_photo, car la photo 1 est le logo)
                missing_photos = []
                for photo_num in range(2, max_photo + 1):
                    if photo_num not in existing_photos:
                        missing_photos.append(f"{restaurant_id}{photo_num}.webp")
                
                if missing_photos:
                    missing_photos_data.append({
                        'Restaurant_ID': restaurant_id,
                        'Photos_Existantes': len(existing_photos),
                        'Photos_Manquantes': ', '.join(missing_photos),
                        'Nombre_Photos_Manquantes': len(missing_photos),
                        'Photos_Detaillees': ' | '.join([f"{restaurant_id}{num}.webp" for num in sorted(existing_photos)])
                    })
            else:
                # Restaurant sans aucune photo
                missing_photos_data.append({
                    'Restaurant_ID': restaurant_id,
                    'Photos_Existantes': 0,
                    'Photos_Manquantes': 'Aucune photo',
                    'Nombre_Photos_Manquantes': 'Aucune',
                    'Photos_Detaillees': 'Aucune'
                })
        
        logger.info(f"❌ Restaurants avec photos manquantes : {len(missing_photos_data)}")
        
        # Création du DataFrame
        df = pd.DataFrame(missing_photos_data)
        
        # Sauvegarde en Excel
        excel_file = "exports/missing_photos_report.xlsx"
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Photos_Manquantes', index=False)
            
            # Ajuster la largeur des colonnes
            worksheet = writer.sheets['Photos_Manquantes']
            worksheet.column_dimensions['A'].width = 15  # Restaurant_ID
            worksheet.column_dimensions['B'].width = 20  # Photos_Existantes
            worksheet.column_dimensions['C'].width = 50  # Photos_Manquantes
            worksheet.column_dimensions['D'].width = 25  # Nombre_Photos_Manquantes
            worksheet.column_dimensions['E'].width = 50  # Photos_Detaillees
        
        # Sauvegarde en CSV aussi
        csv_file = "exports/missing_photos_report.csv"
        df.to_csv(csv_file, index=False, encoding='utf-8')
        
        logger.info(f"💾 Rapport Excel sauvegardé dans : {excel_file}")
        logger.info(f"💾 Rapport CSV sauvegardé dans : {csv_file}")
        
        # Affichage des premiers résultats
        logger.info("🔍 Premiers restaurants avec photos manquantes :")
        for i, row in df.head(10).iterrows():
            logger.info(f"   {i+1}. {row['Restaurant_ID']} - {row['Photos_Manquantes']}")
        
        if len(df) > 10:
            logger.info(f"   ... et {len(df) - 10} autres")
        
        # Résumé
        logger.info("\n" + "="*60)
        logger.info("📋 RÉSUMÉ DE LA VÉRIFICATION")
        logger.info("="*60)
        logger.info(f"   • Total restaurants : {len(restaurant_ids)}")
        logger.info(f"   • Restaurants avec photos : {len(restaurant_photos)}")
        logger.info(f"   • Restaurants avec photos manquantes : {len(missing_photos_data)}")
        logger.info(f"   • Restaurants sans aucune photo : {len([r for r in missing_photos_data if r['Photos_Existantes'] == 0])}")
        logger.info("✅ VÉRIFICATION TERMINÉE")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification : {e}")
        raise

if __name__ == "__main__":
    check_missing_photos()
