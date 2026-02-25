#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export des utilisateurs premium (via RevenueCat) vers Excel.

Parcourt tous les utilisateurs Firebase Auth, verifie leur statut premium
sur RevenueCat, et exporte nom + telephone.

Usage:
  python scripts/export_premium_users.py                  # Environnement prod
  python scripts/export_premium_users.py --env dev        # Environnement dev
  python scripts/export_premium_users.py --env prod       # Environnement prod
"""

import os
import sys
import logging
import argparse
import time
from datetime import datetime
from pathlib import Path

import requests
import pandas as pd
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials, auth

# Ajouter le repertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    EXPORTS_DIR,
    SERVICE_ACCOUNT_PATH,
    SERVICE_ACCOUNT_PATH_DEV,
    SERVICE_ACCOUNT_PATH_PROD,
)

# Charger .env pour la cle RevenueCat
from dotenv import load_dotenv
ENV_PATH = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(ENV_PATH)

REVENUECAT_API_KEY = os.getenv('REVENUECAT_API_KEY', '')
REVENUECAT_API_URL = 'https://api.revenuecat.com/v1/subscribers'
PREMIUM_ENTITLEMENTS = {'premium', 'premium24h'}

# Rate limiting : RevenueCat autorise ~10 req/s
BATCH_SIZE = 10
BATCH_DELAY = 1.1  # secondes entre chaque batch


def setup_logging():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(EXPORTS_DIR / 'export_premium_users.log', encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


def ensure_credentials(env, logger):
    if env == 'dev':
        creds_path = SERVICE_ACCOUNT_PATH_DEV
    elif env == 'prod':
        creds_path = SERVICE_ACCOUNT_PATH_PROD
    else:
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or SERVICE_ACCOUNT_PATH

    if not creds_path or not Path(creds_path).exists():
        raise FileNotFoundError(f"Fichier d'identifiants non trouve : {creds_path}")

    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
    logger.info(f"Identifiants Firebase: {creds_path}")
    return creds_path


def init_firebase(logger):
    """Initialise Firebase Admin SDK."""
    if not firebase_admin._apps:
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or SERVICE_ACCOUNT_PATH
        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin SDK initialise")


def fetch_all_auth_users(logger):
    """Recupere tous les utilisateurs Firebase Auth."""
    logger.info("Recuperation de tous les utilisateurs Firebase Auth...")
    users = []
    for user in auth.list_users().iterate_all():
        users.append(user)
    logger.info(f"{len(users)} utilisateurs Auth recuperes")
    return users


def check_revenuecat_premium(uid, session, logger):
    """Verifie si un utilisateur a un entitlement premium actif sur RevenueCat."""
    url = f"{REVENUECAT_API_URL}/{uid}"
    headers = {
        'Authorization': f'Bearer {REVENUECAT_API_KEY}',
        'Content-Type': 'application/json',
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        entitlements = data.get('subscriber', {}).get('entitlements', {})
        for ent_id, ent_data in entitlements.items():
            if ent_id in PREMIUM_ENTITLEMENTS:
                expires = ent_data.get('expires_date')
                if expires is None:
                    # Lifetime / no expiry
                    return True
                try:
                    exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                    if exp_dt > datetime.now(exp_dt.tzinfo):
                        return True
                except (ValueError, TypeError):
                    pass
        return False
    except requests.RequestException:
        return False


def export_premium_users(logger):
    """Pipeline : Auth users -> RevenueCat check -> Firestore enrichment -> Excel."""
    if not REVENUECAT_API_KEY:
        raise ValueError("REVENUECAT_API_KEY non definie dans .env")

    logger.info(f"Cle RevenueCat: {REVENUECAT_API_KEY[:8]}...")

    # 1. Tous les utilisateurs Firebase Auth
    init_firebase(logger)
    all_users = fetch_all_auth_users(logger)

    # 2. Verifier le statut premium via RevenueCat (par batches)
    logger.info(f"Verification du statut premium sur RevenueCat pour {len(all_users)} utilisateurs...")
    logger.info(f"Estimation: ~{len(all_users) // BATCH_SIZE * BATCH_DELAY:.0f}s")

    premium_uids = set()
    session = requests.Session()

    for i in range(0, len(all_users), BATCH_SIZE):
        batch = all_users[i:i + BATCH_SIZE]
        for user in batch:
            if check_revenuecat_premium(user.uid, session, logger):
                premium_uids.add(user.uid)

        done = min(i + BATCH_SIZE, len(all_users))
        if done % 100 == 0 or done == len(all_users):
            logger.info(f"  {done}/{len(all_users)} verifies, {len(premium_uids)} premium trouves")

        if i + BATCH_SIZE < len(all_users):
            time.sleep(BATCH_DELAY)

    session.close()
    logger.info(f"{len(premium_uids)} utilisateurs premium RevenueCat trouves")

    if not premium_uids:
        logger.warning("Aucun utilisateur premium trouve.")
        return None

    # 3. Enrichir avec Firestore users + Auth pour nom/telephone
    client = firestore.Client()
    auth_map = {}
    for user in all_users:
        if user.uid in premium_uids:
            auth_map[user.uid] = {
                'display_name': str(getattr(user, 'display_name', '') or '').strip(),
                'phone_number': str(getattr(user, 'phone_number', '') or '').strip(),
            }

    # Firestore user profiles
    firestore_map = {}
    for uid in premium_uids:
        try:
            doc = client.collection('users').document(uid).get()
            if doc.exists:
                firestore_map[uid] = doc.to_dict()
        except Exception:
            pass

    # 4. Construire les lignes
    records = []
    for uid in premium_uids:
        fs = firestore_map.get(uid, {})
        au = auth_map.get(uid, {})

        name = (
            fs.get('fullname') or fs.get('full_name') or fs.get('nom')
            or fs.get('name') or fs.get('prenom')
            or au.get('display_name') or ''
        )
        phone = fs.get('phone') or fs.get('phoneNumber') or au.get('phone_number') or ''

        records.append({
            'nom': name,
            'telephone': phone,
        })

    # 5. Export Excel
    df = pd.DataFrame(records)
    df = df.sort_values('nom', ascending=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"utilisateurs_premium_{timestamp}.xlsx"
    output_path = EXPORTS_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)

    logger.info(f"Export Excel cree : {output_path}")
    logger.info(f"{len(df)} utilisateurs premium exportes")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export des utilisateurs premium (via RevenueCat)")
    parser.add_argument('--env', choices=['dev', 'prod'], default='prod',
                        help="Environnement Firebase (defaut: prod)")
    args = parser.parse_args()

    logger = setup_logging()
    try:
        ensure_credentials(args.env, logger)
        path = export_premium_users(logger)
        if path:
            logger.info(f"Fichier : {path.absolute()}")
    except KeyboardInterrupt:
        logger.info("Annule.")
    except Exception as e:
        logger.error(f"Erreur : {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
