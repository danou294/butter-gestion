#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compte le nombre d'inscriptions par méthode d'authentification sur des dates données.

Analyse Firebase Auth (creation_timestamp) et la collection Firestore 'users' (authProvider)
pour croiser la méthode d'inscription : phone, apple, google, email, ou inconnu.

Usage:
  python scripts/signups_by_date.py                          # Hier et aujourd'hui
  python scripts/signups_by_date.py --dates 2026-02-15 2026-02-16
  python scripts/signups_by_date.py --env prod               # Forcer l'environnement prod
"""

import os
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, auth, firestore

# Ajouter le répertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD


def get_service_account_path(env):
    if env == 'dev':
        return SERVICE_ACCOUNT_PATH_DEV
    return SERVICE_ACCOUNT_PATH_PROD


def init_firebase(env):
    """Initialise Firebase Admin SDK."""
    sa_path = get_service_account_path(env)
    if not Path(sa_path).exists():
        print(f"❌ Fichier credentials introuvable : {sa_path}")
        sys.exit(1)

    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = sa_path

    if not firebase_admin._apps:
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred)

    return firestore.client()


def parse_dates(date_strings):
    """Parse les dates fournies en argument."""
    dates = []
    for d in date_strings:
        try:
            dates.append(datetime.strptime(d, '%Y-%m-%d').date())
        except ValueError:
            print(f"❌ Format de date invalide : {d} (attendu: YYYY-MM-DD)")
            sys.exit(1)
    return sorted(dates)


def detect_auth_method(auth_user, firestore_data):
    """
    Détecte la méthode d'authentification d'un utilisateur.

    Priorité :
    1. Champ 'authProvider' dans Firestore (défini par l'app pour Apple/Google)
    2. Provider data de Firebase Auth
    3. Numéro de téléphone = phone
    """
    # 1. Vérifier le champ authProvider dans Firestore
    if firestore_data:
        provider = firestore_data.get('authProvider', '').lower()
        if provider in ('apple', 'google'):
            return provider

    # 2. Vérifier les providers Firebase Auth
    if auth_user.provider_data:
        provider_ids = [p.provider_id for p in auth_user.provider_data]
        if 'apple.com' in provider_ids:
            return 'apple'
        if 'google.com' in provider_ids:
            return 'google'
        if 'phone' in provider_ids:
            return 'phone'
        if 'password' in provider_ids:
            return 'email'

    # 3. Fallback : si le user a un numéro de téléphone
    if auth_user.phone_number:
        return 'phone'

    return 'inconnu'


def main():
    parser = argparse.ArgumentParser(description="Inscriptions par date et méthode d'auth")
    parser.add_argument('--dates', nargs='+', help="Dates à analyser (YYYY-MM-DD)")
    parser.add_argument('--env', choices=['dev', 'prod'], default='prod', help="Environnement Firebase (défaut: prod)")
    args = parser.parse_args()

    # Dates par défaut : hier et aujourd'hui
    if args.dates:
        target_dates = parse_dates(args.dates)
    else:
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        target_dates = [yesterday, today]

    env_label = "🚀 PROD" if args.env == 'prod' else "🔧 DEV"
    print(f"\n{'='*60}")
    print(f"  Inscriptions Butter — {env_label}")
    print(f"  Dates analysées : {', '.join(str(d) for d in target_dates)}")
    print(f"{'='*60}\n")

    # Init Firebase
    client = init_firebase(args.env)

    # Récupérer tous les users Firestore (pour authProvider)
    print("📥 Récupération des utilisateurs Firestore...")
    firestore_users = {}
    for doc in client.collection('users').stream():
        data = doc.to_dict() or {}
        uid = data.get('uid') or doc.id
        firestore_users[uid] = data

    print(f"   → {len(firestore_users)} utilisateurs Firestore")

    # Récupérer tous les users Firebase Auth
    print("📥 Récupération des utilisateurs Firebase Auth...")
    auth_users = []
    for user in auth.list_users().iterate_all():
        auth_users.append(user)

    print(f"   → {len(auth_users)} utilisateurs Auth\n")

    # Analyser par date
    # Structure : { date: { method: [user_info, ...] } }
    results = {d: defaultdict(list) for d in target_dates}
    total_by_date = {d: 0 for d in target_dates}

    for user in auth_users:
        if not user.user_metadata or not user.user_metadata.creation_timestamp:
            continue

        created_at = datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000)
        created_date = created_at.date()

        if created_date not in results:
            continue

        fs_data = firestore_users.get(user.uid)
        method = detect_auth_method(user, fs_data)

        # Info utilisateur pour le détail
        prenom = ''
        if fs_data:
            prenom = fs_data.get('prenom', '')

        user_info = {
            'uid': user.uid,
            'prenom': prenom,
            'phone': user.phone_number or '',
            'email': user.email or '',
            'created_at': created_at.strftime('%H:%M:%S'),
        }

        results[created_date][method].append(user_info)
        total_by_date[created_date] += 1

    # Affichage des résultats
    grand_total = 0
    grand_by_method = defaultdict(int)

    for date in target_dates:
        day_results = results[date]
        day_total = total_by_date[date]
        grand_total += day_total

        print(f"📅 {date.strftime('%A %d %B %Y')} — {day_total} inscription(s)")
        print(f"{'─'*50}")

        if day_total == 0:
            print("   Aucune inscription\n")
            continue

        for method in ['phone', 'apple', 'google', 'email', 'inconnu']:
            users = day_results.get(method, [])
            if not users:
                continue

            grand_by_method[method] += len(users)
            icon = {'phone': '📱', 'apple': '🍎', 'google': '🔵', 'email': '✉️', 'inconnu': '❓'}.get(method, '•')
            print(f"   {icon} {method.upper():10s} : {len(users)} utilisateur(s)")

            for u in users:
                name = u['prenom'] or '—'
                contact = u['phone'] or u['email'] or '—'
                print(f"      • {name:15s} | {contact:20s} | {u['created_at']}")

        print()

    # Résumé global
    if len(target_dates) > 1:
        print(f"{'='*60}")
        print(f"  TOTAL : {grand_total} inscription(s)")
        print(f"{'─'*50}")
        for method in ['phone', 'apple', 'google', 'email', 'inconnu']:
            count = grand_by_method.get(method, 0)
            if count > 0:
                pct = (count / grand_total * 100) if grand_total else 0
                icon = {'phone': '📱', 'apple': '🍎', 'google': '🔵', 'email': '✉️', 'inconnu': '❓'}.get(method, '•')
                print(f"   {icon} {method.upper():10s} : {count:3d}  ({pct:.0f}%)")
        print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
