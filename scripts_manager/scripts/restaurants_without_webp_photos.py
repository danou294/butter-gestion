#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compare les IDs de restaurants (Firestore) avec les fichiers .webp dans Firebase Storage
et liste les restaurants sans aucune photo .webp.

Usage:
  IDs et bucket en dev:
    python scripts_manager/scripts/restaurants_without_webp_photos.py --dev --excel
  IDs depuis Firestore DEV, photos lues depuis le bucket PROD (comparaison dev vs prod):
    python scripts_manager/scripts/restaurants_without_webp_photos.py --dev --bucket-prod --excel
  IDs et bucket en prod:
    python scripts_manager/scripts/restaurants_without_webp_photos.py --prod --excel
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if "--dev" in sys.argv:
    os.environ["FIREBASE_ENV"] = "dev"
elif "--prod" in sys.argv:
    os.environ["FIREBASE_ENV"] = "prod"

from google.cloud import storage
from google.cloud import firestore
from google.oauth2 import service_account

try:
    from config import (
        SERVICE_ACCOUNT_PATH,
        FIREBASE_BUCKET,
        STORAGE_FOLDERS,
        FIREBASE_ENV_LABEL,
        SERVICE_ACCOUNT_PATH_DEV,
        SERVICE_ACCOUNT_PATH_PROD,
        FIREBASE_BUCKET_DEV,
        FIREBASE_BUCKET_PROD,
    )
except ImportError:
    from config.config import (
        SERVICE_ACCOUNT_PATH,
        FIREBASE_BUCKET,
        STORAGE_FOLDERS,
        SERVICE_ACCOUNT_PATH_DEV,
        SERVICE_ACCOUNT_PATH_PROD,
        FIREBASE_BUCKET_DEV,
        FIREBASE_BUCKET_PROD,
    )
    FIREBASE_ENV_LABEL = ""

PHOTOS_PREFIX = STORAGE_FOLDERS.get("photos", "Photos restaurants/")


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s - %(levelname)s - %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    log_dir = Path("exports") if Path("exports").exists() else Path(".")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"restaurants_without_webp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    return logging.getLogger(__name__)


def get_credentials(env="prod"):
    path = SERVICE_ACCOUNT_PATH_DEV if env == "dev" else SERVICE_ACCOUNT_PATH_PROD
    if not os.path.exists(path):
        raise FileNotFoundError(f"Credentials non trouvé : {path}")
    return service_account.Credentials.from_service_account_file(
        path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


def get_restaurant_ids_from_firestore(credentials):
    db = firestore.Client(credentials=credentials, project=credentials.project_id)
    ids = set()
    for doc in db.collection("restaurants").stream():
        ids.add(doc.id)
    return ids


def load_restaurant_ids_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return set(data)
    if isinstance(data, dict) and "ids" in data:
        return set(data["ids"])
    if isinstance(data, dict):
        return set(data.keys())
    return set()


def list_webp_restaurant_ids_in_storage(credentials, bucket_name):
    client = storage.Client(credentials=credentials, project=credentials.project_id)
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=PHOTOS_PREFIX))
    ids_with_webp = set()
    for blob in blobs:
        name = blob.name
        if not name.lower().endswith(".webp"):
            continue
        rel = name[len(PHOTOS_PREFIX) :].lstrip("/")
        base = rel.replace(".webp", "").replace(".WEBP", "")
        for i in range(len(base), 0, -1):
            prefix, suffix = base[:i], base[i:]
            if suffix.isdigit():
                ids_with_webp.add(prefix)
                break
    return ids_with_webp


def main():
    parser = argparse.ArgumentParser(description="Restaurants sans photo .webp sur Firebase Storage.")
    parser.add_argument("--dev", action="store_true", help="Environnement DEV (Firestore + Storage dev).")
    parser.add_argument("--prod", action="store_true", help="Environnement PROD (défaut).")
    parser.add_argument(
        "--bucket-prod",
        action="store_true",
        help="Utiliser le bucket Storage PROD pour lister les .webp (avec --dev = IDs depuis Firestore dev, photos depuis bucket prod).",
    )
    parser.add_argument("--ids-file", type=str, default=None, help="Fichier JSON des IDs (au lieu de Firestore).")
    parser.add_argument("--export", type=str, default=None, help="Fichier de sortie (.xlsx, .json ou .txt).")
    parser.add_argument("--excel", action="store_true", help="Export Excel dans exports/restaurants_sans_photo_webp.xlsx")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs détaillés.")
    args = parser.parse_args()

    logger = setup_logging(verbose=args.verbose)

    # Déterminer env pour les IDs et pour le bucket
    ids_env = "dev" if args.dev else "prod"
    bucket_env = "prod" if args.bucket_prod else ids_env
    bucket_name = FIREBASE_BUCKET_PROD if bucket_env == "prod" else FIREBASE_BUCKET_DEV

    logger.info("Restaurants sans photo .webp")
    logger.info("IDs: Firestore %s  |  Bucket Storage: %s (%s)", ids_env.upper(), bucket_env.upper(), bucket_name)
    if FIREBASE_ENV_LABEL:
        logger.info("Environnement: %s", FIREBASE_ENV_LABEL)

    # Charger les IDs (Firestore ou fichier)
    if args.ids_file:
        if not os.path.exists(args.ids_file):
            logger.error("Fichier non trouvé: %s", args.ids_file)
            return 1
        restaurant_ids = load_restaurant_ids_from_file(args.ids_file)
        logger.info("IDs chargés depuis le fichier: %d restaurants", len(restaurant_ids))
    else:
        creds_ids = get_credentials(ids_env)
        restaurant_ids = get_restaurant_ids_from_firestore(creds_ids)
        logger.info("IDs Firestore (%s): %d restaurants", ids_env, len(restaurant_ids))

    if not restaurant_ids:
        logger.warning("Aucun restaurant trouvé.")
        return 0

    # Lister les .webp dans le bucket (credentials du bucket pour avoir les droits)
    creds_bucket = get_credentials(bucket_env)
    logger.info("Liste des .webp dans le bucket %s...", bucket_name)
    ids_with_webp = list_webp_restaurant_ids_in_storage(creds_bucket, bucket_name)
    logger.info("Restaurants avec au moins une photo .webp (dans ce bucket): %d", len(ids_with_webp))

    without_webp = sorted(restaurant_ids - ids_with_webp)
    logger.info("Restaurants sans aucune photo .webp: %d", len(without_webp))

    if not without_webp:
        logger.info("Aucun restaurant sans photo .webp.")
        export_path = args.export or ("exports/restaurants_sans_photo_webp.xlsx" if args.excel else None)
        if export_path:
            out = Path(export_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() == ".xlsx":
                wb = Workbook()
                ws = wb.active
                ws.title = "Sans_photo_webp"
                ws.append(["Restaurant_ID", "Remarque"])
                ws.column_dimensions["A"].width = 18
                ws.column_dimensions["B"].width = 55
                wb.save(out)
            logger.info("Export vide: %s", out)
        return 0

    for rid in without_webp[:50]:
        logger.info("  %s", rid)
    if len(without_webp) > 50:
        logger.info("  ... et %d autres", len(without_webp) - 50)

    export_path = args.export or ("exports/restaurants_sans_photo_webp.xlsx" if args.excel else None)
    if export_path:
        out = Path(export_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() == ".xlsx":
            remarque = "Aucune photo .webp sur le bucket Storage (comparaison IDs dev vs bucket prod)" if args.bucket_prod and args.dev else "Aucune photo .webp sur Firebase Storage"
            wb = Workbook()
            ws = wb.active
            ws.title = "Sans_photo_webp"
            ws.append(["Restaurant_ID", "Remarque"])
            for rid in without_webp:
                ws.append([rid, remarque])
            ws.column_dimensions["A"].width = 18
            ws.column_dimensions["B"].width = 55
            wb.save(out)
            logger.info("Export Excel: %s (%d lignes)", out, len(without_webp))
        elif out.suffix.lower() == ".json":
            with open(out, "w", encoding="utf-8") as f:
                json.dump(without_webp, f, ensure_ascii=False, indent=2)
            logger.info("Export JSON: %s", out)
        else:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(without_webp))
            logger.info("Export: %s", out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
