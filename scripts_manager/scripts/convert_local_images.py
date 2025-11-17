#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script global de conversion, import et optimisation d'images locales
- Convertit les images locales en WebP
- Optimise les images (compression, redimensionnement, suppression métadonnées)
- Upload sur Firebase Storage

Usage:
  python scripts/convert_local_images.py                    # Menu interactif
  python scripts/convert_local_images.py --source input/photo-firestore
"""

import os
import sys
import io
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from google.cloud import storage
from PIL import Image, ImageOps

# Ajouter le répertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SERVICE_ACCOUNT_PATH, FIREBASE_BUCKET, STORAGE_FOLDERS

# Formats d'images supportés
SUPPORTED_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp')
STORAGE_DESTINATION = STORAGE_FOLDERS.get("photos", "Photos restaurants/")


def setup_logging() -> logging.Logger:
    """Configure le système de logging"""
    os.makedirs('exports', exist_ok=True)
    log_file = f'exports/convert_local_images_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
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
        description='Conversion, import et optimisation d\'images locales',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Menu interactif
  python scripts/convert_local_images.py

  # Conversion avec paramètres par défaut
  python scripts/convert_local_images.py --source input/photo-firestore

  # Conversion avec paramètres personnalisés
  python scripts/convert_local_images.py --source ./photos --max-width 1920 --quality 90
        """
    )
    parser.add_argument(
        '--source', '-s',
        default='input/photo-firestore',
        help="Répertoire source contenant les images (défaut: input/photo-firestore)"
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
        '--overwrite',
        action='store_true',
        help="Écraser les fichiers existants sur Firebase Storage"
    )
    parser.add_argument(
        '--keep-original-name',
        action='store_true',
        help="Conserver le nom original (sinon remplace l'extension par .webp)"
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


def find_images(directory: Path, logger: logging.Logger) -> List[Path]:
    """Trouve toutes les images dans le répertoire"""
    images = []
    for ext in SUPPORTED_FORMATS:
        images.extend(directory.glob(f'*{ext}'))
        images.extend(directory.glob(f'*{ext.upper()}'))
    logger.info(f"{len(images)} images trouvées dans {directory}")
    return sorted(images)


def optimize_image(img: Image.Image, max_width: int, max_height: int, logger: logging.Logger) -> Image.Image:
    """
    Optimise une image pour le web :
    - Supprime les métadonnées EXIF
    - Redimensionne si nécessaire
    - Convertit en RGB si nécessaire
    """
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


def upload_to_firebase(webp_data: bytes, destination_path: str, filename: str, bucket: storage.Bucket, overwrite: bool, logger: logging.Logger) -> bool:
    """Upload une image WebP sur Firebase Storage"""
    try:
        if not destination_path.endswith('/'):
            destination_path += '/'
        blob_path = f"{destination_path}{filename}"
        
        blob = bucket.blob(blob_path)
        if blob.exists() and not overwrite:
            logger.warning(f"   ⏭️  Fichier existe déjà: {blob_path} (utilisez --overwrite pour écraser)")
            return False
        
        blob.upload_from_string(webp_data, content_type='image/webp')
        logger.info(f"   ✅ Uploadé: {blob_path}")
        return True
    except Exception as e:
        logger.error(f"   ❌ Erreur lors de l'upload de {filename}: {e}")
        return False


def process_images(
    images: List[Path],
    destination: str,
    bucket: storage.Bucket,
    max_width: int,
    max_height: int,
    quality: int,
    keep_original_name: bool,
    overwrite: bool,
    logger: logging.Logger
) -> dict:
    """Traite toutes les images"""
    stats = {
        'total': len(images),
        'converted': 0,
        'uploaded': 0,
        'skipped': 0,
        'errors': 0,
        'total_original_size': 0,
        'total_webp_size': 0,
        'total_space_saved': 0,
    }
    
    for i, image_path in enumerate(images, 1):
        logger.info(f"[{i}/{len(images)}] Traitement de {image_path.name}...")
        
        try:
            # Déterminer le nom du fichier de destination
            if keep_original_name:
                dest_filename = image_path.stem + '.webp'
            else:
                if image_path.suffix.lower() == '.webp':
                    dest_filename = image_path.name
                else:
                    dest_filename = image_path.stem + '.webp'
            
            # Lire l'image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Convertir en WebP
            webp_data, conversion_stats = convert_to_webp(
                image_data, max_width, max_height, quality, logger
            )
            
            # Mettre à jour les statistiques
            stats['total_original_size'] += conversion_stats['original_size']
            stats['total_webp_size'] += conversion_stats['webp_size']
            stats['total_space_saved'] += (conversion_stats['original_size'] - conversion_stats['webp_size'])
            stats['converted'] += 1
            
            # Afficher les stats de conversion
            original_mb = conversion_stats['original_size'] / (1024 * 1024)
            webp_mb = conversion_stats['webp_size'] / (1024 * 1024)
            logger.info(f"   📊 {original_mb:.2f} MB → {webp_mb:.2f} MB (-{conversion_stats['reduction_percent']:.1f}%)")
            
            # Upload sur Firebase
            if upload_to_firebase(webp_data, destination, dest_filename, bucket, overwrite, logger):
                stats['uploaded'] += 1
            else:
                stats['skipped'] += 1
                
        except Exception as e:
            logger.error(f"   ❌ Erreur pour {image_path.name}: {e}")
            stats['errors'] += 1
    
    return stats


def show_interactive_menu() -> dict:
    """Affiche un menu interactif pour configurer la conversion"""
    print("\n" + "="*60)
    print("🖼️  CONVERSION, IMPORT ET OPTIMISATION D'IMAGES LOCALES")
    print("="*60)
    
    source = input(f"\n📁 Répertoire source (défaut: input/photo-firestore): ").strip()
    if not source:
        source = 'input/photo-firestore'
    
    max_width = input("📐 Largeur maximale en pixels (défaut: 1920): ").strip()
    max_width = int(max_width) if max_width.isdigit() else 1920
    
    max_height = input("📐 Hauteur maximale en pixels (défaut: 1920): ").strip()
    max_height = int(max_height) if max_height.isdigit() else 1920
    
    quality = input("🎨 Qualité WebP 0-100 (défaut: 85): ").strip()
    quality = int(quality) if quality.isdigit() and 0 <= int(quality) <= 100 else 85
    
    overwrite = input("⚠️  Écraser les fichiers existants ? (o/N): ").strip().lower()
    overwrite = overwrite in ('o', 'oui', 'y', 'yes')
    
    keep_name = input("📝 Conserver le nom original ? (o/N): ").strip().lower()
    keep_name = keep_name in ('o', 'oui', 'y', 'yes')
    
    print(f"\n✅ Configuration:")
    print(f"   📁 Source: {source}")
    print(f"   📐 Dimensions max: {max_width}x{max_height}px")
    print(f"   🎨 Qualité: {quality}%")
    print(f"   ⚠️  Overwrite: {'Oui' if overwrite else 'Non'}")
    print(f"   📝 Nom original: {'Conservé' if keep_name else 'Renommé en .webp'}")
    
    confirm = input("\n🚀 Démarrer la conversion ? (O/n): ").strip().lower()
    if confirm in ('n', 'non', 'no'):
        print("👋 Opération annulée")
        sys.exit(0)
    
    return {
        'source': source,
        'max_width': max_width,
        'max_height': max_height,
        'quality': quality,
        'overwrite': overwrite,
        'keep_original_name': keep_name
    }


def print_summary(stats: dict, logger: logging.Logger):
    """Affiche le résumé des opérations"""
    logger.info("=" * 60)
    logger.info("📊 RÉSUMÉ:")
    logger.info(f"   • Total: {stats['total']}")
    logger.info(f"   • ✅ Converties: {stats['converted']}")
    logger.info(f"   • ☁️  Uploadées: {stats['uploaded']}")
    logger.info(f"   • ⏭️  Ignorées: {stats['skipped']}")
    logger.info(f"   • ❌ Erreurs: {stats['errors']}")
    logger.info(f"   • 📦 Taille originale: {stats['total_original_size'] / (1024 * 1024):.2f} MB")
    logger.info(f"   • 📦 Taille WebP: {stats['total_webp_size'] / (1024 * 1024):.2f} MB")
    logger.info(f"   • 💾 Espace économisé: {stats['total_space_saved'] / (1024 * 1024):.2f} MB")
    
    if stats['total_original_size'] > 0:
        total_reduction = (stats['total_space_saved'] / stats['total_original_size']) * 100
        logger.info(f"   • 📉 Réduction totale: {total_reduction:.1f}%")
    
    logger.info("=" * 60)
    logger.info("✅ TERMINÉ")


def main() -> None:
    """Fonction principale"""
    logger = setup_logging()
    args = parse_args()
    
    try:
        ensure_credentials(logger)
        
        # Configuration
        if not args.source:
            config = show_interactive_menu()
        else:
            config = {
                'source': args.source,
                'max_width': args.max_width,
                'max_height': args.max_height,
                'quality': args.quality,
                'overwrite': args.overwrite,
                'keep_original_name': args.keep_original_name
            }
        
        # Vérifier le répertoire source
        source_dir = Path(config['source'])
        if not source_dir.exists():
            raise FileNotFoundError(f"Répertoire source non trouvé: {source_dir}")
        if not source_dir.is_dir():
            raise ValueError(f"Le chemin source n'est pas un répertoire: {source_dir}")
        
        logger.info("=" * 60)
        logger.info("🚀 CONVERSION, IMPORT ET OPTIMISATION D'IMAGES LOCALES")
        logger.info("=" * 60)
        logger.info(f"📁 Source: {source_dir}")
        logger.info(f"☁️  Destination: {STORAGE_DESTINATION}")
        logger.info(f"📐 Dimensions max: {config['max_width']}x{config['max_height']}px")
        logger.info(f"🎨 Qualité WebP: {config['quality']}%")
        
        # Trouver les images
        images = find_images(source_dir, logger)
        
        if not images:
            logger.warning("Aucune image trouvée dans le répertoire source")
            return
        
        # Connexion à Firebase Storage
        logger.info("🔌 Connexion à Firebase Storage...")
        storage_client = storage.Client()
        bucket = storage_client.bucket(FIREBASE_BUCKET)
        logger.info(f"📦 Bucket: {FIREBASE_BUCKET}")
        
        # Traiter les images
        start_time = time.time()
        stats = process_images(
            images,
            STORAGE_DESTINATION,
            bucket,
            config['max_width'],
            config['max_height'],
            config['quality'],
            config['keep_original_name'],
            config['overwrite'],
            logger
        )
        elapsed_time = time.time() - start_time
        stats['elapsed_time'] = elapsed_time
        
        # Afficher le résumé
        print_summary(stats, logger)
        
        if stats['converted'] > 0:
            logger.info(f"   • ⏱️  Temps: {elapsed_time:.1f} secondes ({elapsed_time/60:.1f} minutes)")
            logger.info(f"   • 🚀 Vitesse: {stats['converted'] / (elapsed_time / 60):.1f} images/min")
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Conversion annulée par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

