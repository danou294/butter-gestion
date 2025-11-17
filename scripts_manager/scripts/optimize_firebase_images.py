#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script global d'optimisation et conversion d'images sur Firebase Storage
- Convertit les PNG en WebP
- Optimise les images existantes (compression, redimensionnement)
- Remplace les images originales par des versions optimisées

Usage:
  python scripts/optimize_firebase_images.py                    # Menu interactif
  python scripts/optimize_firebase_images.py --convert-png --all
  python scripts/optimize_firebase_images.py --optimize-existing
"""

import os
import sys
import io
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from google.cloud import storage
from PIL import Image, ImageOps

# Ajouter le répertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SERVICE_ACCOUNT_PATH, FIREBASE_BUCKET, STORAGE_FOLDERS

STORAGE_DESTINATION = STORAGE_FOLDERS.get("photos", "Photos restaurants/")


def setup_logging() -> logging.Logger:
    """Configure le système de logging"""
    os.makedirs('exports', exist_ok=True)
    log_file = f'exports/optimize_firebase_images_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
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
        description='Optimisation et conversion d\'images sur Firebase Storage',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Menu interactif
  python scripts/optimize_firebase_images.py

  # Convertir tous les PNG en WebP
  python scripts/optimize_firebase_images.py --convert-png --all

  # Convertir uniquement les PNG restants (sans WebP)
  python scripts/optimize_firebase_images.py --convert-png --remaining

  # Optimiser les images existantes
  python scripts/optimize_firebase_images.py --optimize-existing
        """
    )
    parser.add_argument(
        '--convert-png',
        action='store_true',
        help="Convertir les PNG en WebP"
    )
    parser.add_argument(
        '--optimize-existing',
        action='store_true',
        help="Optimiser les images existantes (remplace les originales)"
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help="Convertir TOUS les PNG (mode convert-png)"
    )
    parser.add_argument(
        '--remaining',
        action='store_true',
        help="Convertir uniquement les PNG restants sans WebP (mode convert-png)"
    )
    parser.add_argument(
        '--max-width',
        type=int,
        default=1920,
        help="Largeur maximale en pixels (défaut: 1920)"
    )
    parser.add_argument(
        '--max-height',
        type=int,
        default=1920,
        help="Hauteur maximale en pixels (défaut: 1920)"
    )
    parser.add_argument(
        '--quality',
        type=int,
        default=85,
        help="Qualité WebP (0-100, défaut: 85)"
    )
    parser.add_argument(
        '--delete-png',
        action='store_true',
        help="Supprimer les PNG originaux après conversion"
    )
    return parser.parse_args()


def ensure_credentials(logger: logging.Logger) -> None:
    """Vérifie que les credentials Firebase sont disponibles"""
    creds_path = SERVICE_ACCOUNT_PATH
    if not Path(creds_path).exists():
        raise FileNotFoundError(
            f"Fichier des identifiants non trouvé : {creds_path}\n"
            f"💡 Vérifiez que le fichier existe dans {creds_path}"
        )
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
    logger.info(f"Identifiants Firebase: {creds_path}")


def optimize_image(img: Image.Image, max_width: int, max_height: int, logger: logging.Logger) -> Image.Image:
    """Optimise une image pour le web"""
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    
    original_size = img.size
    if img.size[0] > max_width or img.size[1] > max_height:
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        logger.debug(f"   📐 Redimensionné: {original_size[0]}x{original_size[1]} → {img.size[0]}x{img.size[1]}")
    
    if img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode == 'RGBA':
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    return img


def convert_to_webp(image_data: bytes, max_width: int, max_height: int, quality: int, logger: logging.Logger) -> Tuple[bytes, dict]:
    """Convertit une image en WebP optimisé"""
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            original_size = img.size
            optimized_img = optimize_image(img, max_width, max_height, logger)
            
            webp_buffer = io.BytesIO()
            optimized_img.save(
                webp_buffer,
                format='WebP',
                quality=quality,
                method=6,
                optimize=True
            )
            webp_data = webp_buffer.getvalue()
            
            stats = {
                'original_size': len(image_data),
                'webp_size': len(webp_data),
                'original_dimensions': original_size,
                'webp_dimensions': optimized_img.size,
                'reduction_percent': ((len(image_data) - len(webp_data)) / len(image_data) * 100) if len(image_data) > 0 else 0
            }
            
            return webp_data, stats
    except Exception as e:
        logger.error(f"   ❌ Erreur lors de la conversion: {e}")
        raise


def convert_png_to_webp(all_png: bool, delete_png: bool, max_width: int, max_height: int, quality: int, logger: logging.Logger) -> dict:
    """Convertit les PNG dans Firebase Storage en WebP"""
    logger.info("=" * 60)
    logger.info("🔄 CONVERSION PNG → WEBP DANS FIREBASE STORAGE")
    logger.info("=" * 60)
    
    storage_client = storage.Client()
    bucket = storage_client.bucket(FIREBASE_BUCKET)
    
    logger.info("🔍 Recherche des images PNG...")
    blobs = list(bucket.list_blobs(prefix=STORAGE_DESTINATION))
    png_images = [blob for blob in blobs if not blob.name.endswith('/') and blob.name.lower().endswith('.png')]
    
    logger.info(f"📊 {len(png_images)} images PNG trouvées")
    
    if all_png:
        png_to_convert = png_images
        logger.info("🔄 Mode: Conversion de TOUS les PNG")
    else:
        logger.info("🔍 Vérification des WebP existants...")
        existing_blobs = {blob.name: blob for blob in blobs if not blob.name.endswith('/')}
        png_to_convert = []
        for png_blob in png_images:
            webp_name = png_blob.name.replace('.png', '.webp').replace('.PNG', '.webp')
            if webp_name not in existing_blobs:
                png_to_convert.append(png_blob)
        logger.info("🔄 Mode: Conversion des PNG RESTANTS (sans WebP)")
        logger.info(f"✅ {len(png_to_convert)} PNG à convertir ({len(png_images) - len(png_to_convert)} déjà convertis)")
    
    if not png_to_convert:
        logger.info("✅ Aucune image PNG à convertir")
        return {'total': 0, 'converted': 0, 'errors': 0}
    
    stats = {
        'total': len(png_to_convert),
        'converted': 0,
        'skipped': len(png_images) - len(png_to_convert) if not all_png else 0,
        'errors': 0,
        'total_original_size': 0,
        'total_webp_size': 0,
        'space_saved': 0
    }
    
    start_time = time.time()
    for i, png_blob in enumerate(png_to_convert, 1):
        try:
            logger.info(f"🔄 [{i}/{len(png_to_convert)}] Conversion: {png_blob.name}")
            
            png_data = png_blob.download_as_bytes()
            stats['total_original_size'] += len(png_data)
            
            webp_data, conversion_stats = convert_to_webp(png_data, max_width, max_height, quality, logger)
            stats['total_webp_size'] += len(webp_data)
            stats['space_saved'] += (len(png_data) - len(webp_data))
            
            webp_name = png_blob.name.replace('.png', '.webp').replace('.PNG', '.webp')
            webp_blob = bucket.blob(webp_name)
            webp_blob.upload_from_string(webp_data, content_type='image/webp')
            
            if delete_png:
                png_blob.delete()
                logger.info(f"   🗑️  PNG original supprimé")
            
            png_mb = len(png_data) / (1024 * 1024)
            webp_mb = len(webp_data) / (1024 * 1024)
            reduction = conversion_stats['reduction_percent']
            logger.info(f"   ✅ Converti: {png_mb:.2f} MB → {webp_mb:.2f} MB (-{reduction:.1f}%)")
            stats['converted'] += 1
            
            if i % 10 == 0:
                elapsed = time.time() - start_time
                remaining = (elapsed / i) * (len(png_to_convert) - i)
                logger.info(f"📈 Progression: {i}/{len(png_to_convert)} ({i/len(png_to_convert)*100:.1f}%) - Temps restant: {remaining/60:.1f} min")
        except Exception as e:
            logger.error(f"   ❌ Erreur PNG {png_blob.name}: {e}")
            stats['errors'] += 1
    
    stats['elapsed_time'] = time.time() - start_time
    return stats


def optimize_existing_images(max_width: int, max_height: int, quality: int, logger: logging.Logger) -> dict:
    """Optimise les images existantes en les remplaçant"""
    logger.info("=" * 60)
    logger.info("🚀 OPTIMISATION DES IMAGES EXISTANTES")
    logger.info("=" * 60)
    logger.info("⚠️  ATTENTION: Les images originales seront remplacées par des versions optimisées")
    
    storage_client = storage.Client()
    bucket = storage_client.bucket(FIREBASE_BUCKET)
    
    logger.info("🔍 Recherche des images à optimiser...")
    blobs = list(bucket.list_blobs(prefix=STORAGE_DESTINATION))
    images_to_optimize = [
        blob for blob in blobs 
        if not blob.name.endswith('/') and 
        blob.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
    ]
    
    logger.info(f"📊 {len(images_to_optimize)} images à optimiser")
    
    stats = {
        'total': len(images_to_optimize),
        'processed': 0,
        'errors': 0,
        'total_original_size': 0,
        'total_optimized_size': 0,
        'space_saved': 0
    }
    
    start_time = time.time()
    for i, image_blob in enumerate(images_to_optimize, 1):
        try:
            logger.info(f"🔄 [{i}/{len(images_to_optimize)}] Optimisation: {image_blob.name}")
            
            image_data = image_blob.download_as_bytes()
            stats['total_original_size'] += len(image_data)
            
            # Convertir en WebP optimisé
            webp_data, conversion_stats = convert_to_webp(image_data, max_width, max_height, quality, logger)
            stats['total_optimized_size'] += len(webp_data)
            stats['space_saved'] += (len(image_data) - len(webp_data))
            
            # Remplacer l'image originale
            webp_name = image_blob.name
            if not webp_name.lower().endswith('.webp'):
                webp_name = image_blob.name.rsplit('.', 1)[0] + '.webp'
            
            # Si le nom change, supprimer l'ancien
            if webp_name != image_blob.name:
                image_blob.delete()
            
            # Uploader la version optimisée
            webp_blob = bucket.blob(webp_name)
            webp_blob.upload_from_string(webp_data, content_type='image/webp')
            
            original_mb = len(image_data) / (1024 * 1024)
            webp_mb = len(webp_data) / (1024 * 1024)
            reduction = conversion_stats['reduction_percent']
            logger.info(f"   ✅ Optimisé: {original_mb:.2f} MB → {webp_mb:.2f} MB (-{reduction:.1f}%)")
            stats['processed'] += 1
            
            if i % 10 == 0:
                elapsed = time.time() - start_time
                remaining = (elapsed / i) * (len(images_to_optimize) - i)
                logger.info(f"📈 Progression: {i}/{len(images_to_optimize)} ({i/len(images_to_optimize)*100:.1f}%) - Temps restant: {remaining/60:.1f} min")
        except Exception as e:
            logger.error(f"   ❌ Erreur pour {image_blob.name}: {e}")
            stats['errors'] += 1
    
    stats['elapsed_time'] = time.time() - start_time
    return stats


def show_interactive_menu() -> dict:
    """Affiche un menu interactif pour choisir l'opération"""
    print("\n" + "="*60)
    print("🖼️  OPTIMISATION ET CONVERSION D'IMAGES FIREBASE")
    print("="*60)
    print("\nQuelle opération voulez-vous effectuer ?")
    print("\n" + "-"*60)
    
    print("\n1. Convertir les PNG en WebP")
    print("   - Tous les PNG")
    print("   - Uniquement les PNG restants (sans WebP)")
    
    print("\n2. Optimiser les images existantes")
    print("   - Remplace les images par des versions optimisées")
    
    print("\n3. Quitter")
    print("-"*60)
    
    while True:
        try:
            choice = input(f"\nVotre choix (1-3): ").strip()
            
            if choice == "3" or choice.lower() == "0":
                print("👋 Au revoir !")
                sys.exit(0)
            
            elif choice == "1":
                mode = input("\n📋 Mode de conversion:\n  1. Tous les PNG\n  2. PNG restants uniquement\nChoix (1-2): ").strip()
                all_png = (mode == "1")
                
                delete = input("\n🗑️  Supprimer les PNG originaux après conversion ? (o/N): ").strip().lower()
                delete_png = delete in ('o', 'oui', 'y', 'yes')
                
                print(f"\n✅ Opération sélectionnée : Conversion PNG → WebP ({'Tous' if all_png else 'Restants uniquement'})")
                if delete_png:
                    print("⚠️  Les PNG originaux seront supprimés après conversion")
                
                return {
                    'operation': 'convert_png',
                    'all_png': all_png,
                    'delete_png': delete_png
                }
            
            elif choice == "2":
                print(f"\n✅ Opération sélectionnée : Optimisation des images existantes")
                print("⚠️  Les images originales seront remplacées par des versions optimisées")
                
                return {
                    'operation': 'optimize_existing'
                }
            
            else:
                print("❌ Choix invalide. Veuillez choisir 1, 2 ou 3.")
        
        except KeyboardInterrupt:
            print("\n\n👋 Au revoir !")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Erreur : {e}")
            continue


def print_summary(stats: dict, operation_type: str, logger: logging.Logger):
    """Affiche le résumé des opérations"""
    logger.info("=" * 60)
    logger.info("📊 RÉSUMÉ:")
    logger.info(f"   • Total: {stats.get('total', stats.get('processed', 0))}")
    if 'converted' in stats:
        logger.info(f"   • ✅ Converties: {stats['converted']}")
    if 'processed' in stats:
        logger.info(f"   • ✅ Optimisées: {stats['processed']}")
    if 'skipped' in stats and stats.get('skipped', 0) > 0:
        logger.info(f"   • ⏭️  Ignorées: {stats['skipped']}")
    logger.info(f"   • ❌ Erreurs: {stats.get('errors', 0)}")
    
    if stats.get('total_original_size', 0) > 0:
        optimized_size = stats.get('total_webp_size', stats.get('total_optimized_size', 0))
        logger.info(f"   • 📦 Taille originale: {stats['total_original_size'] / (1024 * 1024):.2f} MB")
        logger.info(f"   • 📦 Taille optimisée: {optimized_size / (1024 * 1024):.2f} MB")
        space_saved = stats.get('space_saved', 0)
        logger.info(f"   • 💾 Espace économisé: {space_saved / (1024 * 1024):.2f} MB")
        
        total_reduction = (space_saved / stats['total_original_size']) * 100
        logger.info(f"   • 📉 Réduction totale: {total_reduction:.1f}%")
    
    if stats.get('elapsed_time'):
        elapsed = stats['elapsed_time']
        logger.info(f"   • ⏱️  Temps: {elapsed:.1f} secondes ({elapsed/60:.1f} minutes)")
        processed = stats.get('converted', stats.get('processed', 0))
        if processed > 0:
            logger.info(f"   • 🚀 Vitesse: {processed / (elapsed / 60):.1f} images/min")
    
    logger.info("=" * 60)
    logger.info("✅ TERMINÉ")


def main() -> None:
    """Fonction principale"""
    logger = setup_logging()
    args = parse_args()
    
    try:
        ensure_credentials(logger)
        
        # Déterminer l'opération
        if not args.convert_png and not args.optimize_existing:
            config = show_interactive_menu()
        else:
            if args.convert_png:
                config = {
                    'operation': 'convert_png',
                    'all_png': args.all,
                    'delete_png': args.delete_png
                }
                if not args.all and not args.remaining:
                    config['all_png'] = False  # Par défaut, restants uniquement
            else:
                config = {'operation': 'optimize_existing'}
        
        # Exécution de l'opération
        logger.info("🚀 Démarrage de l'opération...")
        
        if config['operation'] == 'convert_png':
            stats = convert_png_to_webp(
                config.get('all_png', False),
                config.get('delete_png', False),
                args.max_width,
                args.max_height,
                args.quality,
                logger
            )
            print_summary(stats, "convert_png", logger)
        
        elif config['operation'] == 'optimize_existing':
            stats = optimize_existing_images(
                args.max_width,
                args.max_height,
                args.quality,
                logger
            )
            print_summary(stats, "optimize_existing", logger)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Opération annulée par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

