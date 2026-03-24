#!/usr/bin/env python3
"""
Seed script : ajouter les sections coups_de_coeur et videos dans home_sections.

Pour chaque ville active, crée :
  - { type: "coups_de_coeur", title: "Coups de coeur", order: 1, isActive: true }
  - { type: "videos", title: "Nos dégustations", order: <dernier>, isActive: true }

Et ajoute type: "guides" aux sections existantes qui n'ont pas de type.

Usage :
    python3 seed_home_section_types.py [--env dev|prod] [--dry-run]

Par défaut : env=dev, dry-run activé.
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import firebase_admin
from firebase_admin import credentials, firestore

COLLECTION = "home_sections"
CITIES = ["Paris", "Marrakech"]


def get_service_account_path(env: str) -> str:
    base = Path(__file__).resolve().parent.parent.parent / "firebase_credentials"
    if env == "dev":
        return str(base / "serviceAccountKey.dev.json")
    return str(base / "serviceAccountKey.prod.json")


def init_firebase(env: str):
    sa_path = get_service_account_path(env)
    if not os.path.exists(sa_path):
        print(f"  Service account introuvable : {sa_path}")
        sys.exit(1)
    cred = credentials.Certificate(sa_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def seed(db, dry_run: bool):
    docs = list(db.collection(COLLECTION).stream())
    print(f"  {len(docs)} sections existantes\n")

    # 1. Ajouter type: "guides" aux sections existantes sans type
    migrated = 0
    for doc in docs:
        data = doc.to_dict()
        if 'type' not in data or not data['type']:
            print(f"  [MIGRATE] {doc.id} '{data.get('title', '')}' -> type='guides'")
            if not dry_run:
                db.collection(COLLECTION).document(doc.id).update({
                    'type': 'guides',
                    'updatedAt': datetime.utcnow(),
                })
            migrated += 1

    print(f"\n  {migrated} sections migrées avec type='guides'\n")

    # 2. Pour chaque ville, créer coups_de_coeur et videos si absents
    created = 0
    for city in CITIES:
        city_docs = [d for d in docs if d.to_dict().get('city') == city]
        city_types = {d.to_dict().get('type') for d in city_docs}
        existing_orders = [d.to_dict().get('order', 0) for d in city_docs]
        max_order = max(existing_orders) if existing_orders else -1

        # Coups de coeur en premier (order 0), décaler les guides existants
        if 'coups_de_coeur' not in city_types:
            print(f"  [CREATE] {city}: coups_de_coeur (order=0)")
            if not dry_run:
                # Décaler les sections existantes de +1
                for d in city_docs:
                    data = d.to_dict()
                    db.collection(COLLECTION).document(d.id).update({
                        'order': data.get('order', 0) + 1,
                    })
                db.collection(COLLECTION).add({
                    'title': 'Coups de coeur',
                    'type': 'coups_de_coeur',
                    'order': 0,
                    'isActive': True,
                    'city': city,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                })
                max_order += 1  # account for shift
            created += 1

        # Videos en dernier
        if 'videos' not in city_types:
            video_order = max_order + 1 + (1 if 'coups_de_coeur' not in city_types else 0)
            print(f"  [CREATE] {city}: videos (order={video_order})")
            if not dry_run:
                db.collection(COLLECTION).add({
                    'title': 'Nos dégustations',
                    'type': 'videos',
                    'order': video_order,
                    'isActive': True,
                    'city': city,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                })
            created += 1

    print(f"\n  {created} sections créées")
    if dry_run:
        print("\n  ** DRY RUN — aucune modification effectuée **")


def main():
    parser = argparse.ArgumentParser(description="Seed home_sections types")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Appliquer les changements")
    args = parser.parse_args()

    dry_run = not args.apply
    print(f"\n  Env: {args.env.upper()} | Dry run: {dry_run}\n")

    db = init_firebase(args.env)
    seed(db, dry_run)


if __name__ == "__main__":
    main()
