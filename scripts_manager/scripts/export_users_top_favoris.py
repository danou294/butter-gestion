#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export des utilisateurs ayant plus de 10 favoris actifs vers Excel.

Requiert la collection Firestore 'favorites' (champs: userId, restaurantId, status)
et enrichit avec les donnees de la collection 'users' + Firebase Auth.

Usage:
  python scripts/export_users_top_favoris.py              # Seuil par defaut (10)
  python scripts/export_users_top_favoris.py --min 20     # Seuil personnalise
"""

import os
import sys
import logging
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials, auth

# Ajouter le repertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EXPORTS_DIR, SERVICE_ACCOUNT_PATH


def setup_logging():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(EXPORTS_DIR / 'export_users_top_favoris.log', encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


def ensure_credentials(logger):
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not creds_path and SERVICE_ACCOUNT_PATH:
        creds_path = SERVICE_ACCOUNT_PATH
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
    if not creds_path:
        raise FileNotFoundError("Aucun fichier d'identifiants trouve.")
    if not Path(creds_path).exists():
        raise FileNotFoundError(f"Fichier non trouve : {creds_path}")
    logger.info(f"Identifiants: {creds_path}")


def count_favorites_by_user(client, logger):
    """Compte les favoris actifs par userId."""
    logger.info("Recuperation des favoris...")
    favorites_ref = client.collection('favorites')
    user_counts = defaultdict(int)
    total = 0

    for doc in favorites_ref.stream():
        total += 1
        data = doc.to_dict()
        status = data.get('status', 'active')
        if status != 'inactive':
            user_id = data.get('userId')
            if user_id:
                user_counts[user_id] += 1

    logger.info(f"{total} favoris parcourus, {sum(user_counts.values())} actifs, {len(user_counts)} utilisateurs distincts")
    return user_counts


def fetch_firestore_users(client, user_ids, logger):
    """Recupere les infos utilisateurs depuis la collection 'users'."""
    logger.info(f"Recuperation des profils Firestore pour {len(user_ids)} utilisateurs...")
    users_map = {}

    for uid in user_ids:
        try:
            doc = client.collection('users').document(uid).get()
            if doc.exists:
                users_map[uid] = doc.to_dict()
        except Exception:
            pass

    logger.info(f"{len(users_map)} profils Firestore trouves")
    return users_map


def fetch_auth_users(logger):
    """Recupere les infos Firebase Auth pour tous les utilisateurs."""
    logger.info("Recuperation des donnees Firebase Auth...")
    if not firebase_admin._apps:
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or SERVICE_ACCOUNT_PATH
        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)

    auth_map = {}
    for user in auth.list_users().iterate_all():
        last_sign_in = None
        created_at = None
        if user.user_metadata:
            if user.user_metadata.last_sign_in_timestamp:
                last_sign_in = datetime.fromtimestamp(user.user_metadata.last_sign_in_timestamp / 1000).isoformat()
            if user.user_metadata.creation_timestamp:
                created_at = datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000).isoformat()

        auth_map[user.uid] = {
            'email': str(getattr(user, 'email', '') or '').strip(),
            'display_name': str(getattr(user, 'display_name', '') or '').strip(),
            'phone_number': str(getattr(user, 'phone_number', '') or '').strip(),
            'created_at': created_at,
            'last_sign_in': last_sign_in,
        }

    logger.info(f"{len(auth_map)} utilisateurs Auth recuperes")
    return auth_map


def export_top_users(min_favorites, logger):
    """Pipeline principal : compte, filtre, enrichit, exporte."""
    client = firestore.Client()

    # 1. Compter les favoris par user
    user_counts = count_favorites_by_user(client, logger)

    # 2. Filtrer ceux qui ont plus de min_favorites
    top_users = {uid: count for uid, count in user_counts.items() if count > min_favorites}
    logger.info(f"{len(top_users)} utilisateurs avec plus de {min_favorites} favoris")

    if not top_users:
        logger.warning("Aucun utilisateur ne correspond au critere.")
        return None

    # 3. Enrichir avec Firestore users + Auth
    top_user_ids = list(top_users.keys())
    firestore_users = fetch_firestore_users(client, top_user_ids, logger)
    auth_users = fetch_auth_users(logger)

    # 4. Construire les lignes
    records = []
    for uid, fav_count in sorted(top_users.items(), key=lambda x: x[1], reverse=True):
        fs = firestore_users.get(uid, {})
        au = auth_users.get(uid, {})

        # Nom : essayer plusieurs champs Firestore puis Auth
        name = (
            fs.get('fullname') or fs.get('full_name') or fs.get('nom')
            or fs.get('name') or fs.get('prenom')
            or au.get('display_name') or ''
        )
        email = fs.get('email') or au.get('email') or ''
        phone = fs.get('phone') or fs.get('phoneNumber') or au.get('phone_number') or ''

        records.append({
            'uid': uid,
            'nom': name,
            'email': email,
            'telephone': phone,
            'nb_favoris': fav_count,
            'compte_cree': au.get('created_at', ''),
            'derniere_connexion': au.get('last_sign_in', ''),
        })

    # 5. Export Excel
    df = pd.DataFrame(records)
    df = df.sort_values('nb_favoris', ascending=False)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"users_plus_de_{min_favorites}_favoris_{timestamp}.xlsx"
    output_path = EXPORTS_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)

    logger.info(f"Export Excel cree : {output_path}")
    logger.info(f"{len(df)} utilisateurs exportes")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export des utilisateurs ayant beaucoup de favoris")
    parser.add_argument('--min', type=int, default=10, help="Seuil minimum de favoris (defaut: 10)")
    args = parser.parse_args()

    logger = setup_logging()
    try:
        ensure_credentials(logger)
        path = export_top_users(args.min, logger)
        if path:
            logger.info(f"Fichier : {path.absolute()}")
    except KeyboardInterrupt:
        logger.info("Annule.")
    except Exception as e:
        logger.error(f"Erreur : {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
