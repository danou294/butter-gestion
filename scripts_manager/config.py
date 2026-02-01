#!/usr/bin/env python3
"""
Configuration centralisée pour tous les scripts Firebase
Adapté pour Django
"""

import os
from pathlib import Path

# Chemin de base Django
# config.py est dans scripts_manager/, donc on remonte de 2 niveaux pour arriver à la racine du projet
BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_ROOT = BASE_DIR / 'media'

# Dossier pour les credentials Firebase (à la racine du projet)
FIREBASE_CREDENTIALS_DIR = BASE_DIR / "firebase_credentials"
FIREBASE_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

# Dossiers
INPUT_DIR = MEDIA_ROOT / "input"
INPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPORTS_DIR = MEDIA_ROOT / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# CONFIGURATION FIREBASE
# =============================================================================

# Buckets Firebase Storage (un par environnement)
FIREBASE_BUCKET_DEV = "butter-def.firebasestorage.app"
FIREBASE_BUCKET_PROD = "butter-vdef.firebasestorage.app"

# Collection Firestore
FIRESTORE_COLLECTION = "restaurants"

# =============================================================================
# GESTION DES ENVIRONNEMENTS (DEV/PROD)
# =============================================================================

# Déterminer l'environnement depuis la variable d'environnement ou la session Django
# Par défaut: 'prod' si non défini
# Note: La session Django sera vérifiée dans le context processor
FIREBASE_ENV = os.getenv('FIREBASE_ENV', 'prod').lower()

# Valider que l'environnement est valide
if FIREBASE_ENV not in ['dev', 'prod']:
    import warnings
    warnings.warn(f"FIREBASE_ENV invalide: '{FIREBASE_ENV}'. Utilisation de 'prod' par défaut.")
    FIREBASE_ENV = 'prod'

# Chemins vers les credentials selon l'environnement (dans firebase_credentials/)
SERVICE_ACCOUNT_PATH_DEV = str(FIREBASE_CREDENTIALS_DIR / "serviceAccountKey.dev.json")
SERVICE_ACCOUNT_PATH_PROD = str(FIREBASE_CREDENTIALS_DIR / "serviceAccountKey.prod.json")

# Chemin et bucket selon l'environnement
if FIREBASE_ENV == 'dev':
    SERVICE_ACCOUNT_PATH = SERVICE_ACCOUNT_PATH_DEV
    FIREBASE_BUCKET = FIREBASE_BUCKET_DEV
    FIREBASE_ENV_LABEL = "🔧 DEV"
else:
    SERVICE_ACCOUNT_PATH = SERVICE_ACCOUNT_PATH_PROD
    FIREBASE_BUCKET = FIREBASE_BUCKET_PROD
    FIREBASE_ENV_LABEL = "🚀 PROD"

# Exporter l'environnement actif pour utilisation dans les templates
FIREBASE_ENV_ACTIVE = FIREBASE_ENV

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

