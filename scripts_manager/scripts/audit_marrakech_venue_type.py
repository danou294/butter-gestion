"""
Audit READ-ONLY de la collection restaurants Firestore pour Marrakech.
Affiche la distribution exacte des valeurs venue_type, et identifie les docs
qui devraient être daypass mais ne le sont pas (et inversement).

Usage:
    python scripts_manager/scripts/audit_marrakech_venue_type.py [--env prod|dev]
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import firebase_admin
from firebase_admin import credentials, firestore


def init(env: str):
    cred_path = PROJECT_ROOT / "firebase_credentials" / f"serviceAccountKey.{env}.json"
    if not cred_path.exists():
        raise FileNotFoundError(f"Credentials introuvables: {cred_path}")
    cred = credentials.Certificate(str(cred_path))
    if firebase_admin._apps:
        firebase_admin.delete_app(firebase_admin.get_app())
    firebase_admin.initialize_app(cred)
    return firestore.client(), cred.project_id


def audit(env: str):
    db, project = init(env)
    print(f"\n=== AUDIT Marrakech | env={env} | project={project} ===\n")

    docs = list(db.collection("restaurants").where("city", "==", "Marrakech").stream())
    print(f"Total docs Marrakech : {len(docs)}\n")

    if not docs:
        print("⚠️  Aucun doc Marrakech trouvé. Vérifier le casing de 'city'.")
        # Check other casings
        all_docs = list(db.collection("restaurants").stream())
        city_counter = Counter()
        for d in all_docs:
            data = d.to_dict()
            c = data.get("city", "<missing>")
            city_counter[c] += 1
        print("\nDistribution des city values dans toute la collection :")
        for city, count in city_counter.most_common(20):
            print(f"  [{city!r}] : {count}")
        return

    # Distribution venue_type
    venue_counter = Counter()
    missing_venue = []
    weird_venue = []
    for d in docs:
        data = d.to_dict()
        vt = data.get("venue_type", "<MISSING>")
        venue_counter[vt] += 1
        if vt == "<MISSING>":
            missing_venue.append((d.id, data.get("name", ""), data.get("tag", "")))
        elif vt not in ("restaurant", "hotel", "daypass"):
            weird_venue.append((d.id, vt, data.get("name", ""), data.get("tag", "")))

    print("Distribution venue_type (valeurs exactes, repr) :")
    for vt, count in venue_counter.most_common():
        print(f"  [{vt!r}] : {count}")

    print(f"\nDocs SANS venue_type : {len(missing_venue)}")
    for doc_id, name, tag in missing_venue[:15]:
        print(f"  - {doc_id} | name={name!r} | tag={tag!r}")
    if len(missing_venue) > 15:
        print(f"  ... et {len(missing_venue) - 15} autres")

    print(f"\nDocs avec venue_type NON STANDARD (≠ restaurant/hotel/daypass) : {len(weird_venue)}")
    for doc_id, vt, name, tag in weird_venue[:15]:
        print(f"  - {doc_id} | venue_type={vt!r} | name={name!r} | tag={tag!r}")

    # Sample daypass docs (top 5)
    daypass_docs = [d for d in docs if d.to_dict().get("venue_type") == "daypass"]
    print(f"\n--- Échantillon docs daypass ({len(daypass_docs)} au total) ---")
    for d in daypass_docs[:5]:
        data = d.to_dict()
        print(f"  - {d.id} | name={data.get('name', '')!r} | city={data.get('city', '')!r} | venue_type={data.get('venue_type', '')!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["prod", "dev"], default="prod")
    args = parser.parse_args()
    audit(args.env)
