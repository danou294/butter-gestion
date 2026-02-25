#!/usr/bin/env python3
"""
Script pour compter les photos de chaque restaurant dans Firebase Storage
et écrire photo_count dans le document Firestore correspondant.

Usage (depuis le dossier scripts/) :
    python3 update_photo_count.py [--env dev|prod] [--dry-run]

Par défaut : env=dev, pas de dry-run.
"""

import os
import sys
import re
import argparse
from pathlib import Path

# Ajouter le parent pour les imports Django
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage as gcs


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────
PHOTOS_PREFIX = "Photos restaurants/"
# Le bucket Storage est toujours prod (les photos y sont centralisées)
STORAGE_BUCKET = "butter-vdef.firebasestorage.app"


def get_service_account_path(env: str) -> str:
    base = Path(__file__).resolve().parent.parent.parent / "firebase_credentials"
    if env == "dev":
        return str(base / "serviceAccountKey.dev.json")
    return str(base / "serviceAccountKey.prod.json")


def init_firebase(env: str):
    """Initialise firebase_admin + retourne le client Firestore."""
    sa_path = get_service_account_path(env)
    if not os.path.exists(sa_path):
        print(f"❌ Service account introuvable : {sa_path}")
        sys.exit(1)
    cred = credentials.Certificate(sa_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def get_storage_client() -> gcs.Client:
    """Client GCS — utilise toujours le SA prod (bucket photos = prod)."""
    sa_path = get_service_account_path("prod")
    from google.oauth2 import service_account as sa_mod
    creds = sa_mod.Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return gcs.Client(credentials=creds)


# ─────────────────────────────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────────────────────────────
def count_photos_in_storage() -> dict[str, int]:
    """
    Liste les blobs dans Photos restaurants/ et compte les .webp par TAG.
    Convention : <TAG><numero>.webp  (ex: BOZEN2.webp, BOZEN3.webp …)
    Retourne {TAG: nombre_de_photos} (exclut la photo 1 qui est le logo).
    """
    client = get_storage_client()
    bucket = client.bucket(STORAGE_BUCKET)
    blobs = bucket.list_blobs(prefix=PHOTOS_PREFIX)

    # TAG → set de numéros
    tag_numbers: dict[str, set[int]] = {}

    # Pattern : tout sauf les chiffres finaux = TAG, les chiffres finaux = numéro
    pattern = re.compile(r"^(.+?)(\d+)\.webp$", re.IGNORECASE)

    for blob in blobs:
        filename = blob.name.removeprefix(PHOTOS_PREFIX)
        if not filename:
            continue
        m = pattern.match(filename)
        if not m:
            continue
        tag = m.group(1).upper()
        num = int(m.group(2))
        # On ne compte que les photos (num >= 2), la 1 est dans Logos/
        if num < 2:
            continue
        tag_numbers.setdefault(tag, set()).add(num)

    # Convertir en count
    return {tag: len(nums) for tag, nums in tag_numbers.items()}


def load_firestore_tags(db) -> dict[str, str]:
    """
    Charge tous les restaurants Firestore → {TAG_upper: doc_id}
    """
    docs = db.collection("restaurants").stream()
    mapping = {}
    for doc in docs:
        data = doc.to_dict()
        tag = (data.get("tag") or "").upper()
        if tag:
            mapping[tag] = doc.id
    return mapping


def update_firestore(db, tag_to_docid: dict, photo_counts: dict, dry_run: bool):
    """
    Écrit photo_count dans chaque document restaurant.
    """
    updated = 0
    skipped = 0
    not_found = 0

    for tag, count in sorted(photo_counts.items()):
        doc_id = tag_to_docid.get(tag)
        if not doc_id:
            print(f"  ⚠️  TAG {tag} ({count} photos) — pas trouvé en Firestore")
            not_found += 1
            continue

        if dry_run:
            print(f"  [DRY] {tag} → photo_count={count}")
            updated += 1
        else:
            db.collection("restaurants").document(doc_id).update({"photo_count": count})
            print(f"  ✅ {tag} → photo_count={count}")
            updated += 1

    # Restaurants sans photos dans Storage → photo_count = 5 (défaut actuel)
    for tag, doc_id in tag_to_docid.items():
        if tag not in photo_counts:
            skipped += 1

    return updated, skipped, not_found


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Compte les photos par restaurant et écrit photo_count en Firestore")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev", help="Environnement Firestore (default: dev)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans écrire en Firestore")
    args = parser.parse_args()

    print(f"{'🔧 DRY RUN' if args.dry_run else '🚀 LIVE'} — Firestore env: {args.env}")
    print(f"📦 Storage bucket: {STORAGE_BUCKET}")
    print()

    # 1. Scanner le Storage
    print("📸 Scan du Storage (Photos restaurants/) …")
    photo_counts = count_photos_in_storage()
    print(f"   → {len(photo_counts)} TAGs trouvés avec des photos\n")

    # Stats rapides
    if photo_counts:
        counts = sorted(photo_counts.values())
        print(f"   Min: {counts[0]} | Max: {counts[-1]} | Médiane: {counts[len(counts)//2]}")
        more_than_5 = {t: c for t, c in photo_counts.items() if c > 5}
        if more_than_5:
            print(f"   🎉 {len(more_than_5)} restaurants avec PLUS de 5 photos :")
            for t, c in sorted(more_than_5.items(), key=lambda x: -x[1]):
                print(f"      {t}: {c} photos")
        print()

    # 2. Charger les TAGs Firestore
    print("🔥 Chargement des restaurants Firestore …")
    db = init_firebase(args.env)
    tag_to_docid = load_firestore_tags(db)
    print(f"   → {len(tag_to_docid)} restaurants en Firestore\n")

    # 3. Écrire photo_count
    print("✏️  Mise à jour photo_count …")
    updated, skipped, not_found = update_firestore(db, tag_to_docid, photo_counts, args.dry_run)

    print()
    print("=" * 50)
    print(f"📋 RÉSUMÉ")
    print(f"   Mis à jour : {updated}")
    print(f"   Sans photos Storage (gardent défaut 5) : {skipped}")
    if not_found:
        print(f"   TAGs Storage non trouvés en Firestore : {not_found}")
    print("=" * 50)


if __name__ == "__main__":
    main()
