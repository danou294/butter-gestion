"""
Migration : convertit le champ venue_type de string vers array sur tous les
docs de la collection restaurants.

Avant : venue_type = "hotel"
Après : venue_type = ["hotel"]

Idempotent : les docs déjà en array sont ignorés.

Usage :
    # Audit (read-only) :
    python scripts_manager/scripts/migrate_venue_type_to_array.py --env prod --dry-run

    # Migration réelle (demande confirmation) :
    python scripts_manager/scripts/migrate_venue_type_to_array.py --env prod
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import firebase_admin
from firebase_admin import credentials, firestore

BATCH_SIZE = 400


def init(env: str):
    cred_path = PROJECT_ROOT / "firebase_credentials" / f"serviceAccountKey.{env}.json"
    if not cred_path.exists():
        raise FileNotFoundError(f"Credentials introuvables: {cred_path}")
    cred = credentials.Certificate(str(cred_path))
    if firebase_admin._apps:
        firebase_admin.delete_app(firebase_admin.get_app())
    firebase_admin.initialize_app(cred)
    return firestore.client(), cred.project_id


def scan(db):
    """Retourne (to_migrate, already_array, missing). to_migrate = liste de (doc_id, string_value)."""
    docs = db.collection("restaurants").stream()
    to_migrate = []
    already_array = 0
    missing = 0
    weird = []
    for d in docs:
        data = d.to_dict()
        vt = data.get("venue_type")
        if vt is None or vt == "":
            missing += 1
        elif isinstance(vt, str):
            to_migrate.append((d.id, vt))
        elif isinstance(vt, list):
            already_array += 1
        else:
            weird.append((d.id, type(vt).__name__, repr(vt)))
    return to_migrate, already_array, missing, weird


def migrate(db, to_migrate, log_prefix=""):
    """Effectue la migration en batches. Retourne le nombre de docs patchés."""
    coll = db.collection("restaurants")
    patched = 0
    batch = db.batch()
    count = 0
    for doc_id, vt in to_migrate:
        ref = coll.document(doc_id)
        batch.update(ref, {"venue_type": [vt]})
        count += 1
        patched += 1
        if count >= BATCH_SIZE:
            batch.commit()
            print(f"{log_prefix}  Commit batch ({count} docs)")
            batch = db.batch()
            count = 0
    if count > 0:
        batch.commit()
        print(f"{log_prefix}  Commit batch final ({count} docs)")
    return patched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["prod", "dev"], default="dev")
    parser.add_argument("--dry-run", action="store_true", help="Audit seul, pas d'écriture")
    parser.add_argument("--yes", action="store_true", help="Skip la confirmation (CI)")
    args = parser.parse_args()

    db, project = init(args.env)
    print(f"\n=== Migration venue_type → array ===")
    print(f"Env: {args.env} | Project: {project}")
    print(f"Mode: {'DRY-RUN (lecture seule)' if args.dry_run else 'WRITE'}\n")

    print("Scan en cours...")
    to_migrate, already_array, missing, weird = scan(db)

    type_dist = Counter(vt for _, vt in to_migrate)

    print(f"\nÉtat actuel :")
    print(f"  À migrer (string)      : {len(to_migrate)}")
    print(f"  Déjà en array          : {already_array}")
    print(f"  Sans venue_type        : {missing}")
    print(f"  Type bizarre           : {len(weird)}")
    if weird:
        for doc_id, type_name, val in weird[:5]:
            print(f"    - {doc_id} ({type_name}): {val}")

    if to_migrate:
        print(f"\nDistribution des valeurs string à migrer :")
        for vt, n in type_dist.most_common():
            print(f"  [{vt!r}] : {n}")

    if args.dry_run:
        print(f"\n[DRY-RUN] Aucune écriture effectuée. {len(to_migrate)} docs seraient migrés.")
        return

    if not to_migrate:
        print(f"\n✅ Rien à migrer.")
        return

    if not args.yes:
        print(f"\n⚠️  Cette opération va écrire sur Firestore {project} ({args.env}).")
        print(f"   {len(to_migrate)} docs vont être modifiés.")
        resp = input(f"   Confirmer ? (tape EXACTEMENT 'oui {args.env}') : ").strip()
        if resp != f"oui {args.env}":
            print(f"❌ Confirmation invalide. Abandon.")
            sys.exit(1)

    print(f"\n🚀 Migration en cours...")
    patched = migrate(db, to_migrate)
    print(f"\n✅ Migration terminée : {patched} docs patchés.")


if __name__ == "__main__":
    main()
