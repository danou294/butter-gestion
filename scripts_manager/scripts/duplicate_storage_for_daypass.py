"""
Duplique les logos et photos d'un venue dans Firebase Storage pour permettre
la duplication "hotel + daypass" (Refs distincts pour le même endroit).

Pour chaque tag fourni (ex. SELMAN), copie :
  - Logos/SELMAN*.webp                 → Logos/SELMAN-DP*.webp
  - Photos restaurants/SELMAN*.webp    → Photos restaurants/SELMAN-DP*.webp

Match strict : ne copie QUE les fichiers `{tag}<chiffres>.webp` — pas les
fichiers d'autres venues dont le tag commence pareil.

DEUX MODES :

1. Liste manuelle (--tags) :
    python duplicate_storage_for_daypass.py --env prod --tags SELMAN MFAI MFOU --dry-run
    python duplicate_storage_for_daypass.py --env prod --tags SELMAN MFAI MFOU

2. Auto-détection depuis l'Excel (--excel) :
    Lit les onglets 'Hôtels' et 'Daypass'. Pour chaque Ref en Daypass qui
    finit par le suffixe (ex. SELMAN-DP) et dont le Ref base (SELMAN) existe
    en Hôtels → c'est une paire multi-type → duplique le storage de SELMAN.

    python duplicate_storage_for_daypass.py --env prod --excel /chemin/marrakech.xlsx --dry-run
    python duplicate_storage_for_daypass.py --env prod --excel /chemin/marrakech.xlsx

Suffixe personnalisé (par défaut -DP) :
    python duplicate_storage_for_daypass.py --env prod --tags SELMAN --suffix -DAY
"""
import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import firebase_admin
from firebase_admin import credentials, storage

BUCKETS = {
    "prod": "butter-vdef.firebasestorage.app",
    "dev": "butter-def.firebasestorage.app",
}

PREFIXES = ["Logos/", "Photos restaurants/"]


def init(env: str):
    cred_path = PROJECT_ROOT / "firebase_credentials" / f"serviceAccountKey.{env}.json"
    if not cred_path.exists():
        raise FileNotFoundError(f"Credentials introuvables: {cred_path}")
    cred = credentials.Certificate(str(cred_path))
    if firebase_admin._apps:
        firebase_admin.delete_app(firebase_admin.get_app())
    firebase_admin.initialize_app(cred, {"storageBucket": BUCKETS[env]})
    return storage.bucket(), cred.project_id


def find_blobs_for_tag(bucket, prefix: str, tag: str):
    """Retourne les blobs qui matchent {prefix}{tag}<chiffres>.webp"""
    pattern = re.compile(rf"^{re.escape(prefix)}{re.escape(tag)}(\d+)\.webp$", re.IGNORECASE)
    matches = []
    for blob in bucket.list_blobs(prefix=f"{prefix}{tag}"):
        m = pattern.match(blob.name)
        if m:
            matches.append((blob, m.group(1)))
    return matches


def duplicate_for_tag(bucket, tag: str, suffix: str, dry_run: bool):
    """Duplique tous les blobs Logos/{tag}*.webp et Photos restaurants/{tag}*.webp vers {tag}{suffix}."""
    actions = []
    skipped_existing = 0
    new_tag = f"{tag}{suffix}"
    for prefix in PREFIXES:
        matches = find_blobs_for_tag(bucket, prefix, tag)
        for src_blob, num in matches:
            dst_name = f"{prefix}{new_tag}{num}.webp"
            dst_blob = bucket.blob(dst_name)
            if dst_blob.exists():
                skipped_existing += 1
                actions.append(("SKIP (existe déjà)", src_blob.name, dst_name))
                continue
            actions.append(("COPY", src_blob.name, dst_name))
            if not dry_run:
                bucket.copy_blob(src_blob, bucket, dst_name)
    return actions, skipped_existing


REF_COLUMN_CANDIDATES = ["Ref", "Tag", "REF", "ref", "tag"]


def _extract_refs_from_sheet(xls_path: str, sheet_name: str):
    """Extrait la liste des Refs depuis un onglet Excel. Renvoie une liste de strings MAJUSCULE."""
    import pandas as pd
    df = pd.read_excel(xls_path, sheet_name=sheet_name)
    # Trouver la colonne Ref / Tag
    col = None
    for candidate in REF_COLUMN_CANDIDATES:
        if candidate in df.columns:
            col = candidate
            break
    if col is None:
        raise ValueError(f"Onglet '{sheet_name}' : aucune colonne Ref/Tag trouvée (cherché : {REF_COLUMN_CANDIDATES}). "
                         f"Colonnes disponibles : {list(df.columns)}")
    refs = []
    for v in df[col].dropna():
        s = str(v).strip().upper()
        if s and s not in ("NAN", "NONE"):
            refs.append(s)
    return refs


def detect_multi_type_pairs_from_excel(xls_path: str, suffix: str):
    """
    Lit l'Excel et retourne (base_refs_to_duplicate, info_log).
    Pour chaque Ref X-{suffix} dans l'onglet Daypass tel que X est dans l'onglet Hôtels,
    on retourne X.
    """
    hotels_refs = set(_extract_refs_from_sheet(xls_path, "Hôtels"))
    daypass_refs = set(_extract_refs_from_sheet(xls_path, "Daypass"))
    suffix_upper = suffix.upper()
    pairs = []
    for dp_ref in daypass_refs:
        if dp_ref.endswith(suffix_upper):
            base = dp_ref[: -len(suffix_upper)]
            if base in hotels_refs:
                pairs.append(base)
    pairs.sort()
    info = {
        "hotels_count": len(hotels_refs),
        "daypass_count": len(daypass_refs),
        "pairs_detected": len(pairs),
        "daypass_only": sorted(daypass_refs - {p + suffix_upper for p in pairs}),
        "hotels_only": sorted(hotels_refs - set(pairs)),
    }
    return pairs, info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["prod", "dev"], default="dev")
    parser.add_argument("--tags", nargs="+",
                        help="Liste manuelle de tags base à dupliquer (ex. --tags SELMAN MFAI MFOU)")
    parser.add_argument("--excel",
                        help="Chemin vers l'Excel — auto-détecte les paires base/base-{suffix} entre onglets Hôtels et Daypass")
    parser.add_argument("--suffix", default="-DP",
                        help="Suffixe pour la copie (défaut : -DP)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Prévisualise sans rien copier")
    parser.add_argument("--yes", action="store_true",
                        help="Skip la confirmation interactive")
    args = parser.parse_args()

    if not args.tags and not args.excel:
        parser.error("Fournir soit --tags soit --excel.")
    if args.tags and args.excel:
        parser.error("--tags et --excel sont exclusifs.")

    # Mode liste manuelle ou auto-détection
    if args.excel:
        print(f"\n📋 Auto-détection depuis : {args.excel}")
        try:
            tags, info = detect_multi_type_pairs_from_excel(args.excel, args.suffix)
        except Exception as e:
            print(f"❌ Erreur lecture Excel : {e}")
            sys.exit(1)
        print(f"   Onglet Hôtels : {info['hotels_count']} Refs")
        print(f"   Onglet Daypass : {info['daypass_count']} Refs")
        print(f"   Paires multi-type détectées (Ref dans Hôtels + Ref{args.suffix} dans Daypass) : {info['pairs_detected']}")
        if not tags:
            print(f"\n⚠️  Aucune paire détectée. Vérifie que :")
            print(f"     - Tu as ajouté les venues multi-type dans Daypass avec suffixe '{args.suffix}'")
            print(f"     - Les Refs de base existent dans Hôtels")
            sys.exit(0)
    else:
        tags = [t.strip().upper() for t in args.tags if t.strip()]

    bucket, project = init(args.env)
    print(f"\n=== Duplication Storage pour multi-type ===")
    print(f"Env: {args.env} | Bucket: {bucket.name} | Project: {project}")
    print(f"Tags ({len(tags)}): {', '.join(tags)}")
    print(f"Suffixe: '{args.suffix}'")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}\n")

    # Préview / exécution
    total_copy = 0
    total_skip = 0
    for tag in tags:
        actions, skipped = duplicate_for_tag(bucket, tag, args.suffix, dry_run=True)
        if not actions:
            print(f"⚠️  [{tag}] Aucun fichier trouvé.")
            continue
        print(f"[{tag}] → [{tag}{args.suffix}] :")
        for action, src, dst in actions:
            symbol = "✅" if action == "COPY" else "⏭️ "
            print(f"  {symbol} {action}: {src} → {dst}")
            if action == "COPY":
                total_copy += 1
            else:
                total_skip += 1
        print()

    print(f"\nRésumé : {total_copy} copies à faire, {total_skip} déjà existantes (skip).")

    if args.dry_run or total_copy == 0:
        print(f"\n[DRY-RUN] Aucune écriture effectuée." if args.dry_run else "\n✅ Rien à copier.")
        return

    if not args.yes:
        resp = input(f"\nConfirmer les {total_copy} copies sur {args.env} ? (tape 'oui {args.env}') : ").strip()
        if resp != f"oui {args.env}":
            print("❌ Abandon.")
            sys.exit(1)

    print(f"\n🚀 Copie en cours...")
    actual_copy = 0
    for tag in tags:
        actions, _ = duplicate_for_tag(bucket, tag, args.suffix, dry_run=False)
        for action, src, dst in actions:
            if action == "COPY":
                actual_copy += 1
    print(f"\n✅ Terminé : {actual_copy} fichiers copiés.")


if __name__ == "__main__":
    main()
