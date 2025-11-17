#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour supprimer toutes les photos qui se terminent par '1.webp' 
dans le dossier Firebase Storage "Photos restaurants/"

Ce script supprime uniquement les photos se terminant par '1.webp' sur Firebase Storage.

Usage:
  python scripts/delete_photos_not_ending_with_1.py
  python scripts/delete_photos_not_ending_with_1.py --dry-run  # Simulation sans supprimer
"""

import os
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from google.cloud import storage

# Configuration Firebase Storage
FIREBASE_BUCKET = "butter-vdef.firebasestorage.app"
STORAGE_DESTINATION = "Photos restaurants/"


def setup_logging() -> logging.Logger:
    """Configure le système de logging"""
    os.makedirs('exports', exist_ok=True)
    log_file = f'exports/delete_photos_not_ending_with_1_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande"""
    parser = argparse.ArgumentParser(
        description='Supprimer les photos qui se terminent par 1.webp sur Firebase Storage'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Mode simulation : affiche ce qui serait supprimé sans supprimer réellement"
    )
    return parser.parse_args()


def ensure_credentials(logger: logging.Logger) -> None:
    """Vérifie que les credentials Firebase sont disponibles"""
    creds_path = 'input/serviceAccountKey.json'
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
    if not Path(os.environ['GOOGLE_APPLICATION_CREDENTIALS']).exists():
        raise FileNotFoundError(
            f"Fichier des identifiants non trouvé : {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}"
        )
    logger.info(f"Identifiants Firebase: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")


def find_photos_on_firebase(bucket: storage.Bucket, destination: str, logger: logging.Logger) -> List[str]:
    """
    Trouve toutes les photos sur Firebase Storage qui se terminent par '1.webp'
    et retourne leurs chemins complets
    """
    logger.info(f"🔍 Recherche des photos dans {destination}...")
    
    # Lister tous les blobs dans le dossier
    blobs = list(bucket.list_blobs(prefix=destination))
    
    photos_to_delete = []
    all_photos = []
    
    for blob in blobs:
        if blob.name.endswith('/'):
            continue  # Ignorer les dossiers
        
        filename = blob.name.split('/')[-1].lower()
        
        # Vérifier si c'est une image WebP qui se termine par '1.webp'
        if filename.endswith('.webp') and filename.endswith('1.webp'):
            photos_to_delete.append(blob.name)
        elif filename.endswith(('.webp', '.png', '.jpg', '.jpeg')):
            all_photos.append(blob.name)
    
    logger.info(f"📊 Photos totales trouvées: {len(all_photos)}")
    logger.info(f"❌ Photos à supprimer (se terminent par 1.webp): {len(photos_to_delete)}")
    logger.info(f"✅ Photos à garder: {len(all_photos) - len(photos_to_delete)}")
    
    return photos_to_delete


def delete_photos_from_firebase(photo_paths: List[str], bucket: storage.Bucket, dry_run: bool, logger: logging.Logger) -> dict:
    """Supprime les photos sur Firebase Storage"""
    stats = {
        'total': len(photo_paths),
        'deleted': 0,
        'errors': 0,
        'total_size': 0,
    }
    
    for i, photo_path in enumerate(photo_paths, 1):
        try:
            blob = bucket.blob(photo_path)
            
            if not blob.exists():
                logger.warning(f"[{i}/{len(photo_paths)}] ⚠️  Fichier n'existe pas: {photo_path}")
                continue
            
            # Récupérer la taille (peut être None pour certains blobs)
            file_size = blob.size
            if file_size is None:
                # Recharger le blob pour obtenir les métadonnées complètes
                blob.reload()
                file_size = blob.size or 0
            
            stats['total_size'] += file_size
            filename = photo_path.split('/')[-1]
            
            size_display = f"{file_size / 1024:.2f} KB" if file_size > 0 else "taille inconnue"
            
            if dry_run:
                logger.info(f"[{i}/{len(photo_paths)}] [DRY-RUN] Supprimerait: {filename} ({size_display})")
            else:
                blob.delete()
                logger.info(f"[{i}/{len(photo_paths)}] ✅ Supprimé: {filename} ({size_display})")
                stats['deleted'] += 1
                
        except Exception as e:
            logger.error(f"[{i}/{len(photo_paths)}] ❌ Erreur pour {photo_path}: {e}")
            stats['errors'] += 1
    
    return stats


def main() -> None:
    """Fonction principale"""
    logger = setup_logging()
    args = parse_args()
    
    try:
        logger.info("=" * 60)
        logger.info("🗑️  SUPPRESSION DES PHOTOS SE TERMINANT PAR '1.webp' SUR FIREBASE STORAGE")
        logger.info("=" * 60)
        
        # Vérifier les credentials
        ensure_credentials(logger)
        
        # Connexion à Firebase Storage
        logger.info("🔌 Connexion à Firebase Storage...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(FIREBASE_BUCKET)
        logger.info(f"📦 Bucket: {FIREBASE_BUCKET}")
        logger.info(f"📁 Dossier: {STORAGE_DESTINATION}")
        
        if args.dry_run:
            logger.info("🔍 MODE SIMULATION (--dry-run) : aucune suppression réelle")
        else:
            logger.info("⚠️  MODE RÉEL : les fichiers seront supprimés définitivement sur Firebase Storage")
        
        # Trouver les photos à supprimer
        photos_to_delete = find_photos_on_firebase(bucket, STORAGE_DESTINATION, logger)
        
        if not photos_to_delete:
            logger.info("✅ Aucune photo à supprimer")
            return
        
        # Afficher quelques exemples
        logger.info("\n📋 Exemples de photos à supprimer:")
        for photo_path in photos_to_delete[:10]:
            filename = photo_path.split('/')[-1]
            logger.info(f"   • {filename}")
        if len(photos_to_delete) > 10:
            logger.info(f"   ... et {len(photos_to_delete) - 10} autres")
        
        # Demander confirmation si mode réel
        if not args.dry_run:
            logger.info("\n⚠️  ATTENTION : Cette opération est irréversible !")
            logger.info(f"   {len(photos_to_delete)} fichiers seront supprimés définitivement sur Firebase Storage")
            response = input("\n   Continuer ? (oui/non): ").strip().lower()
            if response not in ('oui', 'o', 'yes', 'y'):
                logger.info("❌ Opération annulée")
                return
        
        # Supprimer les photos
        logger.info("\n🗑️  Suppression en cours...")
        stats = delete_photos_from_firebase(photos_to_delete, bucket, args.dry_run, logger)
        
        # Afficher le résumé
        logger.info("=" * 60)
        logger.info("📊 RÉSUMÉ:")
        logger.info(f"   • Total photos à supprimer: {stats['total']}")
        if args.dry_run:
            logger.info(f"   • [SIMULATION] Photos qui seraient supprimées: {stats['total']}")
        else:
            logger.info(f"   • ✅ Photos supprimées: {stats['deleted']}")
            logger.info(f"   • ❌ Erreurs: {stats['errors']}")
        logger.info(f"   • 📦 Taille totale: {stats['total_size'] / (1024 * 1024):.2f} MB")
        logger.info("=" * 60)
        
        if args.dry_run:
            logger.info("💡 Pour supprimer réellement, relancez sans --dry-run")
        else:
            logger.info("✅ TERMINÉ")
        
    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()

