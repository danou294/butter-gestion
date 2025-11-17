#!/usr/bin/env python3
"""
Configuration centralisée pour tous les scripts Firebase
Adapté pour Django
"""

import os
from pathlib import Path

# Chemin de base Django
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MEDIA_ROOT = BASE_DIR / 'media'

# Dossiers
INPUT_DIR = MEDIA_ROOT / "input"
INPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPORTS_DIR = MEDIA_ROOT / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# CONFIGURATION FIREBASE
# =============================================================================

# Bucket Firebase Storage
FIREBASE_BUCKET = "butter-vdef.firebasestorage.app"

# Collection Firestore
FIRESTORE_COLLECTION = "restaurants"

# Chemin vers les credentials (dans media/input pour Django)
SERVICE_ACCOUNT_PATH = str(INPUT_DIR / "serviceAccountKey.json")

# =============================================================================
# CONFIGURATION DES DOSSIERS
# =============================================================================

# Dossiers Firebase Storage
STORAGE_FOLDERS = {
    "logos": "Logos/",
    "photos": "Photos restaurants/",
    "menus": "Menus/"
}

# Dossiers locaux (adaptés pour Django)
LOCAL_FOLDERS = {
    "exports": str(MEDIA_ROOT / "exports"),
    "backup": str(MEDIA_ROOT / "exports" / "backups"),
    "input": str(MEDIA_ROOT / "input")
}

# Dossier de backup pour les imports
BACKUP_DIR = LOCAL_FOLDERS["backup"]
# Créer le dossier s'il n'existe pas
Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)

# =============================================================================
# CONFIGURATION DES SEUILS
# =============================================================================

# Seuils de taille (en bytes)
SIZE_THRESHOLDS = {
    "heavy_image": 500 * 1024,  # 500KB
    "very_heavy_image": 2 * 1024 * 1024,  # 2MB
    "max_image_size": 5 * 1024 * 1024  # 5MB
}

# =============================================================================
# CONFIGURATION DES FORMATS
# =============================================================================

# Formats d'images supportés
SUPPORTED_IMAGE_FORMATS = [".png", ".jpg", ".jpeg", ".webp"]

# Formats de sortie
OUTPUT_FORMATS = {
    "excel": ".xlsx",
    "csv": ".csv",
    "json": ".json",
    "txt": ".txt",
    "log": ".log"
}

# =============================================================================
# CONFIGURATION DU LOGGING
# =============================================================================

# Format des logs
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Niveau de log par défaut
DEFAULT_LOG_LEVEL = 'INFO'

# =============================================================================
# CONFIGURATION DES OPTIMISATIONS
# =============================================================================

# Paramètres d'optimisation des images
OPTIMIZATION_SETTINGS = {
    "webp_quality": 85,
    "png_compression_level": 7,
    "max_width": 1920,
    "max_height": 1080,
    "preserve_transparency": True
}

