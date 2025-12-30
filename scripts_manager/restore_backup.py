#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fonctions pour restaurer les backups de restaurants
"""

import os
import json
import logging
import datetime
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any

import firebase_admin
from firebase_admin import credentials, firestore

from config import BACKUP_DIR, FIRESTORE_COLLECTION

# NOTE: BACKUP_DIR pointe vers media/exports/backups/
# Les backups sont créés lors de l'import avec le format: restaurants_YYYYMMDD_HHMMSS/
# Ce même chemin est utilisé pour la restauration

logger = logging.getLogger(__name__)

BATCH_SIZE = 400


def init_firestore(request=None):
    """
    Initialise Firestore avec le bon environnement
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Utiliser firebase_utils pour obtenir le bon chemin selon l'environnement
    try:
        from scripts_manager.firebase_utils import get_service_account_path
        service_account_path = get_service_account_path(request)
    except ImportError:
        # Fallback si firebase_utils n'est pas disponible
        from config import SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD
        import os
        env = os.getenv('FIREBASE_ENV', 'prod').lower()
        if env == 'dev':
            service_account_path = SERVICE_ACCOUNT_PATH_DEV
        else:
            service_account_path = SERVICE_ACCOUNT_PATH_PROD
    
    if not os.path.exists(service_account_path):
        raise FileNotFoundError(f"Service account introuvable: {service_account_path}")
    
    logger.info(f"🔑 Utilisation du service account: {service_account_path}")
    cred = credentials.Certificate(service_account_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def list_available_backups() -> List[Dict[str, Any]]:
    """
    Liste tous les backups disponibles
    
    Les backups sont créés lors de l'import dans: media/exports/backups/
    Format des dossiers: restaurants_YYYYMMDD_HHMMSS/
    Chaque backup contient: restaurants.json, restaurants.ndjson, backup_meta.json
    
    Returns:
        Liste de dictionnaires avec les infos de chaque backup
    """
    backups = []
    # BACKUP_DIR = media/exports/backups/ (même chemin utilisé lors de l'import)
    backup_path = Path(BACKUP_DIR)
    
    logger.info(f"📂 Recherche des backups dans: {BACKUP_DIR}")
    
    if not backup_path.exists():
        logger.warning(f"Le dossier de backup n'existe pas: {BACKUP_DIR}")
        return backups
    
    # Parcourir tous les dossiers de backup
    for backup_folder in sorted(backup_path.iterdir(), reverse=True):
        if not backup_folder.is_dir():
            continue
        
        # Vérifier si c'est un dossier de backup (format: restaurants_YYYYMMDD_HHMMSS)
        if not backup_folder.name.startswith(f"{FIRESTORE_COLLECTION}_"):
            continue
        
        meta_path = backup_folder / "backup_meta.json"
        if not meta_path.exists():
            # Essayer de trouver un fichier JSON dans le dossier
            json_files = list(backup_folder.glob(f"{FIRESTORE_COLLECTION}.json"))
            if not json_files:
                continue
            
            # Créer des métadonnées basiques
            backup_info = {
                "backup_dir": str(backup_folder),
                "backup_name": backup_folder.name,
                "timestamp": backup_folder.name.replace(f"{FIRESTORE_COLLECTION}_", ""),
                "count": 0,
                "has_meta": False,
                "size": sum(f.stat().st_size for f in backup_folder.rglob('*') if f.is_file()),
            }
        else:
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                backup_info = {
                    "backup_dir": str(backup_folder),
                    "backup_name": backup_folder.name,
                    "timestamp": meta.get("timestamp", backup_folder.name.replace(f"{FIRESTORE_COLLECTION}_", "")),
                    "count": meta.get("count", 0),
                    "has_meta": True,
                    "json_file": meta.get("json"),
                    "ndjson_file": meta.get("ndjson"),
                    "csv_file": meta.get("csv"),
                    "sha256_json": meta.get("sha256_json"),
                    "sha256_ndjson": meta.get("sha256_ndjson"),
                    "size": sum(f.stat().st_size for f in backup_folder.rglob('*') if f.is_file()),
                }
            except Exception as e:
                logger.error(f"Erreur lors de la lecture de {meta_path}: {e}")
                continue
        
        backups.append(backup_info)
    
    return backups


def get_backup_info(backup_dir: str) -> Optional[Dict[str, Any]]:
    """
    Récupère les informations détaillées d'un backup
    
    Args:
        backup_dir: Chemin du dossier de backup
        
    Returns:
        Dictionnaire avec les infos du backup ou None
    """
    backup_path = Path(backup_dir)
    if not backup_path.exists():
        return None
    
    meta_path = backup_path / "backup_meta.json"
    info = {
        "backup_dir": str(backup_path),
        "backup_name": backup_path.name,
        "exists": True,
    }
    
    if meta_path.exists():
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            info.update(meta)
            info["has_meta"] = True
        except Exception as e:
            logger.error(f"Erreur lors de la lecture de {meta_path}: {e}")
            info["has_meta"] = False
    else:
        info["has_meta"] = False
    
    # Vérifier les fichiers disponibles
    json_file = backup_path / f"{FIRESTORE_COLLECTION}.json"
    ndjson_file = backup_path / f"{FIRESTORE_COLLECTION}.ndjson"
    csv_file = backup_path / f"{FIRESTORE_COLLECTION}.csv"
    
    info["has_json"] = json_file.exists()
    info["has_ndjson"] = ndjson_file.exists()
    info["has_csv"] = csv_file.exists()
    
    if json_file.exists():
        info["json_size"] = json_file.stat().st_size
    if ndjson_file.exists():
        info["ndjson_size"] = ndjson_file.stat().st_size
    if csv_file.exists():
        info["csv_size"] = csv_file.stat().st_size
    
    return info


def delete_collection(db, collection_name: str, batch_size: int, log_file: str = None) -> int:
    """Supprime une collection Firestore"""
    total_deleted = 0
    log_func = logger.info if not log_file else lambda msg: print(msg) or logger.info(msg)
    
    while True:
        docs = list(db.collection(collection_name).limit(batch_size).stream())
        if not docs:
            break
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
        total_deleted += len(docs)
        log_func(f"🗑️  Supprimés cumulés: {total_deleted}")
    
    return total_deleted


def import_records_from_backup(db, collection_name: str, records: List[Dict[str, Any]], batch_size: int, log_file: str = None) -> int:
    """Importe des enregistrements depuis un backup"""
    imported = 0
    skipped = 0
    collection = db.collection(collection_name)
    log_func = logger.info if not log_file else lambda msg: print(msg) or logger.info(msg)
    
    for doc in records:
        rid = (doc.get("id") or "").strip()
        if not rid or not isinstance(doc, dict):
            skipped += 1
            continue
        
        try:
            # Retirer l'id du document (il sera utilisé comme ID du document)
            doc_data = {k: v for k, v in doc.items() if k != "id"}
            doc_ref = collection.document(rid)
            doc_ref.set(doc_data, merge=True)
            imported += 1
            if imported % 50 == 0:
                log_func(f"📥 Importés: {imported}")
        except Exception as e:
            logger.error(f"❌ Erreur doc {rid}: {e}")
            skipped += 1
            continue
    
    log_func(f"📥 Import terminé: {imported} importés, {skipped} ignorés")
    return imported


def restore_from_backup(backup_dir: str, create_backup_before: bool = True, request=None) -> Dict[str, Any]:
    """
    Restaure un backup dans Firestore
    
    Args:
        backup_dir: Chemin du dossier de backup
        create_backup_before: Si True, crée un backup de l'état actuel avant restauration
        request: Objet request Django (optionnel) pour déterminer l'environnement Firebase
        
    Returns:
        Dictionnaire avec le résultat de la restauration
    """
    backup_path = Path(backup_dir)
    if not backup_path.exists():
        raise FileNotFoundError(f"Le dossier de backup n'existe pas: {backup_dir}")
    
    # Chercher le fichier de backup (priorité: ndjson > json)
    ndjson_file = backup_path / f"{FIRESTORE_COLLECTION}.ndjson"
    json_file = backup_path / f"{FIRESTORE_COLLECTION}.json"
    
    backup_file = None
    use_ndjson = False
    
    if ndjson_file.exists():
        backup_file = ndjson_file
        use_ndjson = True
    elif json_file.exists():
        backup_file = json_file
        use_ndjson = False
    else:
        raise FileNotFoundError(f"Aucun fichier de backup trouvé dans {backup_dir}")
    
    logger.info(f"📂 Restauration depuis: {backup_file}")
    
    # Lire les données du backup
    records = []
    if use_ndjson:
        logger.info("📖 Lecture du fichier NDJSON...")
        with open(backup_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️  Ligne JSON invalide ignorée: {e}")
    else:
        logger.info("📖 Lecture du fichier JSON...")
        with open(backup_file, 'r', encoding='utf-8') as f:
            records = json.load(f)
    
    logger.info(f"✅ {len(records)} enregistrements chargés depuis le backup")
    
    if not records:
        raise ValueError("Le backup ne contient aucun enregistrement")
    
    # Initialiser Firestore
    db = init_firestore(request)
    
    # Créer un backup de l'état actuel si demandé
    backup_before_dir = None
    if create_backup_before:
        try:
            from import_restaurants import export_collection, ensure_dir
            ts_dir = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_before_dir = os.path.join(BACKUP_DIR, f"{FIRESTORE_COLLECTION}_before_restore_{ts_dir}")
            ensure_dir(backup_before_dir)
            log_file_before = os.path.join(backup_before_dir, "restore_backup.log")
            logger.info(f"🗄️  Création d'un backup de sécurité avant restauration...")
            export_collection(db, FIRESTORE_COLLECTION, backup_before_dir, log_file_before)
            logger.info(f"✅ Backup de sécurité créé: {backup_before_dir}")
        except Exception as e:
            logger.error(f"⚠️  Erreur lors de la création du backup de sécurité: {e}")
            backup_before_dir = None
    
    # Supprimer la collection actuelle
    logger.info(f"🧹 Suppression de la collection '{FIRESTORE_COLLECTION}'...")
    deleted = delete_collection(db, FIRESTORE_COLLECTION, BATCH_SIZE)
    logger.info(f"✅ {deleted} documents supprimés")
    
    # Importer les données du backup
    logger.info(f"🚚 Import de {len(records)} documents depuis le backup...")
    imported = import_records_from_backup(db, FIRESTORE_COLLECTION, records, BATCH_SIZE)
    logger.info(f"✅ {imported} documents importés")
    
    return {
        "success": True,
        "imported": imported,
        "backup_dir": backup_dir,
        "backup_before_dir": backup_before_dir,
        "total_records": len(records),
    }
