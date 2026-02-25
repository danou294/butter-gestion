#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extrait tous les numéros de téléphone des utilisateurs Firebase (prod).

Parcourt Firebase Auth + Firestore (collection 'users') et exporte
en Excel avec nom, prénom, email.

Usage:
  python scripts/export_user_phones.py              # Prod (défaut)
  python scripts/export_user_phones.py --env dev   # Dev
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional
from datetime import datetime

import pandas as pd
import firebase_admin
from firebase_admin import credentials, auth
from google.cloud import firestore

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import EXPORTS_DIR, SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD


def get_service_account_path(env):
    if env == 'dev':
        return SERVICE_ACCOUNT_PATH_DEV
    return SERVICE_ACCOUNT_PATH_PROD


def extract_phone(profile: dict, auth_user=None) -> Optional[str]:
    """Extrait le numéro de téléphone du profil Firestore ou Auth."""
    for key in ('phone', 'phoneNumber', 'telephone', 'tel'):
        value = profile.get(key)
        if value:
            return str(value).strip()
    if auth_user and getattr(auth_user, 'phone_number', None):
        return auth_user.phone_number
    return None


def extract_name(profile: dict, auth_user=None) -> str:
    """Extrait le nom complet (prénom + nom) du profil Firestore ou Auth."""
    prenom = profile.get('prenom') or profile.get('firstName') or ''
    nom = profile.get('nom') or profile.get('lastName') or profile.get('name') or ''
    fullname = profile.get('fullname') or profile.get('full_name') or ''
    if fullname:
        return str(fullname).strip()
    parts = [str(prenom).strip(), str(nom).strip()]
    combined = ' '.join(p for p in parts if p).strip()
    if combined:
        return combined
    if auth_user and getattr(auth_user, 'display_name', None):
        return str(auth_user.display_name).strip()
    return ''


def init_firebase(env: str) -> firestore.Client:
    """Initialise Firebase Admin SDK et retourne le client Firestore."""
    sa_path = get_service_account_path(env)
    if not Path(sa_path).exists():
        print(f"❌ Fichier credentials introuvable : {sa_path}")
        sys.exit(1)

    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = sa_path

    if not firebase_admin._apps:
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred)

    return firestore.Client()


def main():
    parser = argparse.ArgumentParser(description="Extrait les numéros de téléphone des utilisateurs Firebase")
    parser.add_argument('--env', choices=['dev', 'prod'], default='prod', help="Environnement (défaut: prod)")
    parser.add_argument('-o', '--output', help="Fichier de sortie (défaut: exports/user_phones_TIMESTAMP.xlsx)")
    args = parser.parse_args()

    env = args.env
    print(f"📱 Extraction des numéros de téléphone — Environnement: {env.upper()}\n")

    # Init Firebase
    client = init_firebase(env)
    print("✅ Firebase initialisé\n")

    # 1. Récupérer tous les users Firestore
    print("📚 Récupération des utilisateurs Firestore...")
    firestore_users = {}
    for doc in client.collection('users').stream():
        firestore_users[doc.id] = doc.to_dict()
    print(f"   → {len(firestore_users)} utilisateurs Firestore\n")

    # 2. Récupérer tous les users Firebase Auth
    print("🔐 Récupération des utilisateurs Firebase Auth...")
    auth_users = {}
    for user in auth.list_users().iterate_all():
        auth_users[user.uid] = user
    print(f"   → {len(auth_users)} utilisateurs Auth\n")

    # 3. Extraire les téléphones (priorité Firestore puis Auth)
    seen_phones = set()
    results = []  # [(uid, phone, nom, prenom, email), ...]

    for uid, auth_user in auth_users.items():
        profile = firestore_users.get(uid, {})
        phone = extract_phone(profile, auth_user)
        if phone and phone not in seen_phones:
            nom = extract_name(profile, auth_user)
            prenom = profile.get('prenom') or profile.get('firstName') or ''
            email = profile.get('email') or (auth_user.email if auth_user else '') or ''
            results.append((uid, phone, nom, prenom, email))
            seen_phones.add(phone)

    # Users Firestore sans Auth (orphelins)
    for uid, profile in firestore_users.items():
        if uid in auth_users:
            continue
        phone = extract_phone(profile, None)
        if phone and phone not in seen_phones:
            nom = extract_name(profile, None)
            prenom = profile.get('prenom') or profile.get('firstName') or ''
            email = profile.get('email') or ''
            results.append((uid, phone, nom, prenom, email))
            seen_phones.add(phone)

    print(f"📊 {len(results)} numéros de téléphone trouvés\n")

    # 4. Export Excel
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    default_name = f"user_phones_{timestamp}.xlsx"
    out_path = Path(args.output) if args.output else EXPORTS_DIR / default_name
    out_path = out_path.resolve()
    if out_path.suffix.lower() != '.xlsx':
        out_path = out_path.with_suffix('.xlsx')

    df = pd.DataFrame(
        results,
        columns=['uid', 'telephone', 'nom', 'prenom', 'email']
    )
    df = df.sort_values('nom', ascending=True, na_position='last')

    df.to_excel(out_path, index=False, engine='openpyxl')

    print(f"✅ Export terminé : {out_path}")
    print(f"   {len(results)} lignes (uid, telephone, nom, prenom, email)")


if __name__ == '__main__':
    main()
