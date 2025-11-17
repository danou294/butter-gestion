#!/usr/bin/env python3
"""
Configuration centralisée pour tous les scripts Firebase
"""

# =============================================================================
# CONFIGURATION FIREBASE
# =============================================================================

# Bucket Firebase Storage
FIREBASE_BUCKET = "butter-vdef.firebasestorage.app"

# Collection Firestore
FIRESTORE_COLLECTION = "restaurants"

# Chemin vers les credentials
SERVICE_ACCOUNT_PATH = "input/serviceAccountKey.json"

# =============================================================================
# CONFIGURATION DES DOSSIERS
# =============================================================================

# Dossiers Firebase Storage
STORAGE_FOLDERS = {
    "logos": "Logos/",
    "photos": "Photos restaurants/",
    "menus": "Menus/"
}

# Dossiers locaux
LOCAL_FOLDERS = {
    "exports": "../exports/",
    "backup": "../exports/logos_backup/",
    "input": "../../input/"
}

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
# CONFIGURATION DES HORAIRES
# =============================================================================

# Mapping des jours
DAYS_MAPPING = {
    'monday': 'Lundi', 'lundi': 'Lundi',
    'tuesday': 'Mardi', 'mardi': 'Mardi', 
    'wednesday': 'Mercredi', 'mercredi': 'Mercredi',
    'thursday': 'Jeudi', 'jeudi': 'Jeudi',
    'friday': 'Vendredi', 'vendredi': 'Vendredi',
    'saturday': 'Samedi', 'samedi': 'Samedi',
    'sunday': 'Dimanche', 'dimanche': 'Dimanche'
}

# Ordre des jours
DAYS_ORDER = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

# =============================================================================
# CONFIGURATION DES PATTERNS
# =============================================================================

# Patterns de fichiers
FILE_PATTERNS = {
    "logo": r"^([A-Z]+)\d+\.png$",  # ID1.png, ID2.png, etc.
    "photo": r"^([A-Z]+)\d+\.webp$",  # ID1.webp, ID2.webp, etc.
    "restaurant_id": r"^[A-Z]+$"  # ABR, CHEZ, etc.
}

# =============================================================================
# CONFIGURATION DU LOGGING
# =============================================================================

# Format des logs
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Niveau de log par défaut
DEFAULT_LOG_LEVEL = 'INFO'

# =============================================================================
# CONFIGURATION DES RAPPORTS
# =============================================================================

# Colonnes par défaut pour les rapports Excel
DEFAULT_EXCEL_COLUMNS = {
    "missing_photos": ["restaurant_id", "missing_photos", "total_expected", "status"],
    "heavy_images": ["file_path", "size_bytes", "size_mb", "folder", "optimization_needed"],
    "conversion": ["original_file", "converted_file", "size_before", "size_after", "reduction_percent"]
}

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

# =============================================================================
# CONFIGURATION DES BATCHES
# =============================================================================

# Tailles de batch pour les opérations en lot
BATCH_SIZES = {
    "firestore_read": 100,
    "firestore_write": 50,
    "storage_list": 1000,
    "image_processing": 10
}

# =============================================================================
# CONFIGURATION DES TIMEOUTS
# =============================================================================

# Timeouts pour les opérations réseau
TIMEOUTS = {
    "firestore": 30,
    "storage": 60,
    "image_processing": 120
}

# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def format_size(size_bytes):
    """Convertit les bytes en format lisible"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

def get_log_file_path(script_name):
    """Génère le chemin du fichier de log"""
    return f"{LOCAL_FOLDERS['exports']}{script_name}.log"

def get_export_file_path(filename):
    """Génère le chemin du fichier d'export"""
    return f"{LOCAL_FOLDERS['exports']}{filename}"

def is_heavy_image(size_bytes):
    """Vérifie si une image est considérée comme lourde"""
    return size_bytes > SIZE_THRESHOLDS["heavy_image"]

def is_very_heavy_image(size_bytes):
    """Vérifie si une image est très lourde"""
    return size_bytes > SIZE_THRESHOLDS["very_heavy_image"]

# =============================================================================
# CONFIGURATION DES SCRIPTS
# =============================================================================

# Scripts par catégorie
SCRIPT_CATEGORIES = {
    "database": [
        "check_missing_photos.py",
        "check_missing_logos.py", 
        "get_restaurant_ids.py",
        "export-bdd-butter.py",
        "hours_normalizer.py"
    ],
    "photos": [
        "analyze_heavy_images.py",
        "convert_png_to_webp.py",
        "convert_to_webp.py",
        "optimize_logos_firebase.py",
        "verify_png_webp_equivalents.py",
        "delete_png_from_photos.py"
    ],
    "exploration": [
        "explore_storage.py",
        "explore_storage_detailed.py",
        "list_storage_directories.py"
    ],
    "utilities": [
        "debug_hours.py",
        "extract_hours_formats.py",
        "test_hours_parsing.py"
    ]
}

# =============================================================================
# VALIDATION DE LA CONFIGURATION
# =============================================================================

def validate_config():
    """Valide que la configuration est correcte"""
    import os
    
    errors = []
    
    # Vérifier le fichier de credentials
    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        errors.append(f"Service account non trouvé : {SERVICE_ACCOUNT_PATH}")
        errors.append("💡 Copiez votre fichier de credentials Firebase dans input/serviceAccountKey.json")
        errors.append("💡 Voir input/README.md pour plus d'informations")
    
    # Vérifier les dossiers locaux
    for name, path in LOCAL_FOLDERS.items():
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                errors.append(f"Impossible de créer le dossier {name} : {path} - {e}")
    
    if errors:
        print("❌ Erreurs de configuration :")
        for error in errors:
            print(f"  • {error}")
        return False
    
    print("✅ Configuration validée")
    return True

if __name__ == "__main__":
    validate_config()
