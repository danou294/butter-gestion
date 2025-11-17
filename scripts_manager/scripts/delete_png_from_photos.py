#!/usr/bin/env python3
"""
Script pour supprimer tous les fichiers PNG du dossier 'Photos restaurants/' 
dans Firebase Storage, en préservant les dossiers Logos/ et Menu/
"""

import os
import logging
from google.cloud import storage
from google.oauth2 import service_account
import json
from datetime import datetime

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('../exports/delete_png_log.txt'),
        logging.StreamHandler()
    ]
)

def delete_png_from_photos_folder():
    """Supprime tous les fichiers PNG du dossier Photos restaurants/"""
    
    try:
        # Configuration des credentials
        credentials_path = '../../input/serviceAccountKey.json'
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        
        # Initialisation du client Storage
        client = storage.Client(credentials=credentials)
        bucket_name = 'butter-vdef.firebasestorage.app'
        bucket = client.bucket(bucket_name)
        
        logging.info("🔍 Début de la suppression des fichiers PNG")
        logging.info(f"🪣 Bucket utilisé : {bucket_name}")
        logging.info(f"📁 Dossier cible : Photos restaurants/")
        
        # Lister tous les blobs dans Photos restaurants/
        blobs = bucket.list_blobs(prefix='Photos restaurants/')
        
        png_files = []
        other_files = []
        
        # Séparer les fichiers PNG des autres
        for blob in blobs:
            if blob.name.endswith('.png'):
                png_files.append(blob)
            else:
                other_files.append(blob)
        
        logging.info(f"📊 Fichiers trouvés dans Photos restaurants/ :")
        logging.info(f"   • PNG à supprimer : {len(png_files)}")
        logging.info(f"   • Autres fichiers (WebP, etc.) : {len(other_files)}")
        
        if not png_files:
            logging.info("✅ Aucun fichier PNG trouvé à supprimer")
            return
        
        # Log des informations de sécurité
        logging.info(f"⚠️  ATTENTION : Suppression de {len(png_files)} fichiers PNG")
        logging.info("📁 Dossier cible : Photos restaurants/")
        logging.info("🛡️  Dossiers protégés : Logos/, Menu/")
        logging.info("📋 Exemples de fichiers qui seront supprimés :")
        for i, blob in enumerate(png_files[:5]):
            logging.info(f"   • {blob.name}")
        if len(png_files) > 5:
            logging.info(f"   • ... et {len(png_files) - 5} autres")
        
        # Confirmation automatique pour l'environnement non-interactif
        logging.info("✅ Confirmation automatique activée pour l'environnement non-interactif")
        
        # Supprimer les fichiers PNG
        deleted_count = 0
        errors = []
        
        logging.info("🗑️  Début de la suppression...")
        
        for i, blob in enumerate(png_files):
            try:
                blob.delete()
                deleted_count += 1
                
                if (i + 1) % 100 == 0:
                    logging.info(f"   Supprimé {i + 1}/{len(png_files)} fichiers PNG")
                    
            except Exception as e:
                error_msg = f"Erreur lors de la suppression de {blob.name}: {str(e)}"
                logging.error(error_msg)
                errors.append(error_msg)
        
        # Résumé final
        logging.info("=" * 60)
        logging.info("📋 RÉSUMÉ DE LA SUPPRESSION")
        logging.info("=" * 60)
        logging.info(f"   • Fichiers PNG supprimés : {deleted_count}")
        logging.info(f"   • Erreurs : {len(errors)}")
        logging.info(f"   • Autres fichiers préservés : {len(other_files)}")
        
        if errors:
            logging.warning("⚠️  Erreurs rencontrées :")
            for error in errors[:5]:  # Afficher seulement les 5 premières erreurs
                logging.warning(f"   • {error}")
            if len(errors) > 5:
                logging.warning(f"   • ... et {len(errors) - 5} autres erreurs")
        
        logging.info("✅ SUPPRESSION TERMINÉE")
        logging.info(f"💾 Logs sauvegardés dans : ../exports/delete_png_log.txt")
        
    except Exception as e:
        logging.error(f"❌ Erreur générale : {str(e)}")
        raise

if __name__ == "__main__":
    delete_png_from_photos_folder()
