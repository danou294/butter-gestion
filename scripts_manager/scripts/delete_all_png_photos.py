#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour supprimer tous les PNG du dossier Photos restaurants/
"""

import os
import logging
from datetime import datetime
from google.cloud import storage

def setup_logging():
    """Configure le système de logging"""
    os.makedirs('exports', exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('exports/delete_png_photos.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def delete_all_png():
    """Supprime tous les PNG du dossier Photos restaurants/"""
    
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'input/serviceAccountKey.json'
    logger = setup_logging()
    
    logger.info("🗑️  SUPPRESSION DE TOUS LES PNG")
    logger.info("=" * 50)
    
    try:
        # Connexion Firebase
        logger.info("🔌 Connexion à Firebase Storage...")
        storage_client = storage.Client()
        bucket_name = "butter-vdef.firebasestorage.app"
        bucket = storage_client.bucket(bucket_name)
        
        # Lister uniquement les PNG
        logger.info("🔍 Recherche des images PNG...")
        blobs = list(bucket.list_blobs(prefix="Photos restaurants/"))
        png_images = [blob for blob in blobs if not blob.name.endswith('/') and 
                     blob.name.lower().endswith('.png')]
        
        logger.info(f"📊 {len(png_images)} images PNG trouvées")
        
        if not png_images:
            logger.info("✅ Aucune image PNG à supprimer")
            return
        
        # Statistiques
        stats = {
            'deleted': 0,
            'errors': 0,
            'total_size': 0
        }
        
        for i, png_blob in enumerate(png_images, 1):
            try:
                logger.info(f"🗑️  [{i}/{len(png_images)}] Suppression: {png_blob.name}")
                
                # Obtenir la taille avant suppression
                blob = bucket.blob(png_blob.name)
                if blob.size:
                    stats['total_size'] += blob.size
                
                # Supprimer le PNG
                png_blob.delete()
                
                logger.info(f"   ✅ Supprimé")
                stats['deleted'] += 1
                
                # Log de progression
                if i % 10 == 0:
                    logger.info(f"📈 Progression: {i}/{len(png_images)} ({i/len(png_images)*100:.1f}%)")
            
            except Exception as e:
                logger.error(f"   ❌ Erreur PNG {png_blob.name}: {e}")
                stats['errors'] += 1
        
        # Résumé final
        logger.info("=" * 50)
        logger.info("📊 RÉSUMÉ DE LA SUPPRESSION:")
        logger.info(f"   • PNG supprimés: {stats['deleted']}")
        logger.info(f"   • Erreurs: {stats['errors']}")
        logger.info(f"   • Espace libéré: {stats['total_size'] / (1024 * 1024):.2f} MB")
        
        # Sauvegarder le rapport
        with open('exports/delete_png_photos_report.txt', 'w', encoding='utf-8') as f:
            f.write(f"RAPPORT DE SUPPRESSION PNG\n")
            f.write(f"Dossier: Photos restaurants/\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"PNG supprimés: {stats['deleted']}\n")
            f.write(f"Erreurs: {stats['errors']}\n")
            f.write(f"Espace libéré: {stats['total_size'] / (1024 * 1024):.2f} MB\n")
        
        logger.info("✅ SUPPRESSION TERMINÉE")
        logger.info(f"💾 Rapport sauvegardé dans: exports/delete_png_photos_report.txt")
        
    except Exception as e:
        logger.error(f"❌ Erreur générale: {e}")
        raise

if __name__ == "__main__":
    delete_all_png()

