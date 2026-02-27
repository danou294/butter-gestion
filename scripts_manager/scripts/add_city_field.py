#!/usr/bin/env python3
"""
Migration script : ajouter city + venue_type aux restaurants existants.

Ajoute `city: "Paris"` et `venue_type: "restaurant"` a tous les documents
de la collection `restaurants` qui n'ont pas encore ces champs.

Usage (depuis le dossier scripts/) :
    python3 add_city_field.py [--env dev|prod] [--dry-run]

Par defaut : env=dev, dry-run active.
"""

import os
import sys
import argparse
from pathlib import Path

# Ajouter le parent pour les imports Django
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import firebase_admin
from firebase_admin import credentials, firestore


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────
COLLECTION = "restaurants"
BATCH_SIZE = 400


def get_service_account_path(env: str) -> str:
    base = Path(__file__).resolve().parent.parent.parent / "firebase_credentials"
    if env == "dev":
        return str(base / "serviceAccountKey.dev.json")
    return str(base / "serviceAccountKey.prod.json")


def init_firebase(env: str):
    """Initialise firebase_admin + retourne le client Firestore."""
    sa_path = get_service_account_path(env)
    if not os.path.exists(sa_path):
        print(f"  Service account introuvable : {sa_path}")
        sys.exit(1)
    cred = credentials.Certificate(sa_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ─────────────────────────────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────────────────────────────
def migrate_restaurants(db, dry_run: bool):
    """
    Parcourt tous les restaurants et ajoute city + venue_type
    si ces champs sont absents.
    """
    docs = list(db.collection(COLLECTION).stream())
    total = len(docs)
    print(f"   {total} restaurants trouves en Firestore\n")

    already_has_city = 0
    already_has_venue = 0
    to_update = []

    for doc in docs:
        data = doc.to_dict()
        tag = data.get("tag", doc.id)
        has_city = "city" in data and data["city"]
        has_venue = "venue_type" in data and data["venue_type"]

        if has_city:
            already_has_city += 1
        if has_venue:
            already_has_venue += 1

        # Construire l'update seulement pour les champs manquants
        update = {}
        if not has_city:
            update["city"] = "Paris"
        if not has_venue:
            update["venue_type"] = "restaurant"

        if update:
            to_update.append((doc.id, tag, update))

    print(f"   Deja city      : {already_has_city}/{total}")
    print(f"   Deja venue_type : {already_has_venue}/{total}")
    print(f"   A mettre a jour : {len(to_update)}/{total}\n")

    if not to_update:
        print("   Rien a faire, tous les documents ont deja les champs.")
        return 0

    # Appliquer les updates par batch
    updated = 0
    batch = db.batch()
    batch_count = 0

    for doc_id, tag, update in to_update:
        fields_str = ", ".join(f"{k}={v}" for k, v in update.items())

        if dry_run:
            print(f"  [DRY] {tag} ({doc_id}) -> {fields_str}")
        else:
            ref = db.collection(COLLECTION).document(doc_id)
            batch.update(ref, update)
            batch_count += 1

            if batch_count >= BATCH_SIZE:
                batch.commit()
                print(f"  ... batch commit ({batch_count} docs)")
                batch = db.batch()
                batch_count = 0

        updated += 1

    # Commit le dernier batch
    if not dry_run and batch_count > 0:
        batch.commit()
        print(f"  ... batch commit final ({batch_count} docs)")

    return updated


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Ajoute city + venue_type aux restaurants existants en Firestore"
    )
    parser.add_argument(
        "--env", choices=["dev", "prod"], default="dev",
        help="Environnement Firestore (default: dev)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Affiche sans ecrire en Firestore (actif par defaut)"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Execute reellement les modifications (desactive dry-run)"
    )
    args = parser.parse_args()

    # --execute desactive le dry-run
    dry_run = not args.execute

    print("=" * 55)
    print(f"  MIGRATION : ajout city + venue_type")
    print(f"  Mode     : {'DRY RUN (simulation)' if dry_run else 'EXECUTION REELLE'}")
    print(f"  Env      : {args.env.upper()}")
    print("=" * 55)
    print()

    if not dry_run and args.env == "prod":
        confirm = input("  ATTENTION : modification PROD ! Taper 'oui' pour confirmer : ")
        if confirm.strip().lower() != "oui":
            print("  Annule.")
            return

    # 1. Init Firebase
    print("  Connexion Firestore ...")
    db = init_firebase(args.env)

    # 2. Migration
    print(f"  Scan de la collection '{COLLECTION}' ...")
    updated = migrate_restaurants(db, dry_run)

    # 3. Resume
    print()
    print("=" * 55)
    print(f"  RESUME")
    print(f"  Documents {'a modifier' if dry_run else 'modifies'} : {updated}")
    if dry_run:
        print(f"  Pour executer : python3 add_city_field.py --env {args.env} --execute")
    print("=" * 55)


if __name__ == "__main__":
    main()
