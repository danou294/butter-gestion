#!/usr/bin/env python3
"""
full_audit_filters.py
=====================
Comprehensive GROUP BY audit of ALL filter-related fields in Firestore `restaurants`
collection for BOTH dev (butter-def) and prod (butter-vdef) environments.

For each field: flatten arrays, count every unique value, sort by count descending.
Compare with Flutter UI values from search_page.dart, highlighting mismatches.
"""

import os
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")

import firebase_admin
from firebase_admin import credentials, firestore

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
CREDS_DIR = BASE_DIR / "firebase_credentials"

ENVS = {
    "PROD (butter-vdef)": CREDS_DIR / "serviceAccountKey.prod.json",
    "DEV (butter-def)":   CREDS_DIR / "serviceAccountKey.dev.json",
}

# ── Fields to audit ──────────────────────────────────────────────────────────

AUDIT_FIELDS = [
    "cuisine_tag",
    "moment_tag",
    "lieu_tag",
    "price_range",
    "ambiance",
    "preferences_tag",
    "recommended_by_tag",
    "extras",
    "type_tag",
    "has_terrace",
]

# ── Flutter UI values (from search_page.dart) ────────────────────────────────

UI_VALUES = {
    "moment_tag": {
        "label": "Moments UI",
        "values": [
            'Petit-dejeuner', 'Brunch', 'Dejeuner', 'Gouter', 'Drinks', 'Diner',
        ],
        "display": [
            'Petit-dejeuner', 'Brunch', 'Dejeuner', 'Gouter', 'Drinks', 'Diner',
        ],
    },
    "cuisine_tag": {
        "label": "Cuisines UI (base + extra)",
        "values": [
            'Italien', 'Mediterraneen', 'Asiatique', 'Francais',
            'Sud-Americain', 'Chinois', 'Coreen', 'Americain',
            'Japonais', 'Indien', 'Africain', 'Thai',
        ],
        "display": [
            'Italien', 'Mediterraneen', 'Asiatique', 'Francais',
            'Sud-Americain', 'Chinois', 'Coreen', 'Americain',
            'Japonais', 'Indien', 'Africain', 'Thai',
        ],
    },
    "price_range": {
        "label": "Prix UI",
        "values": ['€', '€€', '€€€', '€€€€'],
        "display": ['€', '€€', '€€€', '€€€€'],
    },
    "lieu_tag": {
        "label": "Types d'endroit UI (base + extra)",
        "values": [
            'Bar', 'Restaurant', 'Cave a manger', 'Coffee shop', 'Terrasse', 'Fast',
            'Brasserie', 'Hotel', 'Gastronomique',
        ],
        "display": [
            'Bar', 'Restaurant', 'Cave a manger', 'Coffee shop', 'Terrasse', 'Fast',
            'Brasserie', 'Hotel', 'Gastronomique',
        ],
    },
    "ambiance": {
        "label": "Ambiance UI",
        "values": ['Entre amis', 'En famille', 'Date', 'Festif'],
        "display": ['Entre amis', 'En famille', 'Date', 'Festif'],
    },
    "preferences_tag": {
        "label": "Restrictions UI",
        "values": ['Casher', '100% vegetarien', 'Healthy'],
        "display": ['Casher', '100% vegetarien', 'Healthy'],
    },
}

# Build the raw UI display values (before normalization) for reference
UI_RAW_DISPLAY = {
    "moment_tag": [
        'Petit-dejeuner', 'Brunch', 'Dejeuner', 'Gouter', 'Drinks', 'Diner',
    ],
    "cuisine_tag": [
        'Italien', 'Mediterraneen', 'Asiatique', 'Francais',
        'Sud-Americain', 'Chinois', 'Coreen', 'Americain',
        'Japonais', 'Indien', 'Africain', 'Thai',
    ],
    "price_range": ['€', '€€', '€€€', '€€€€'],
    "lieu_tag": [
        'Bar', 'Restaurant', 'Cave a manger', 'Coffee shop', 'Terrasse', 'Fast',
        'Brasserie', 'Hotel', 'Gastronomique',
    ],
    "ambiance": ['Entre amis', 'En famille', 'Date', 'Festif'],
    "preferences_tag": ['Casher', '100% vegetarien', 'Healthy'],
}

# The ORIGINAL UI strings before any normalization (as they appear in search_page.dart)
UI_ORIGINAL = {
    "moment_tag": [
        'Petit-d\u00e9jeuner', 'Brunch', 'D\u00e9jeuner', 'Go\u00fbter', 'Drinks', 'D\u00eener',
    ],
    "cuisine_tag": [
        'Italien', 'M\u00e9diterran\u00e9en', 'Asiatique', 'Fran\u00e7ais',
        'Sud-Am\u00e9ricain', 'Chinois', 'Cor\u00e9en', 'Am\u00e9ricain',
        'Japonais', 'Indien', 'Africain', 'Tha\u00ef',
    ],
    "price_range": ['\u20ac', '\u20ac\u20ac', '\u20ac\u20ac\u20ac', '\u20ac\u20ac\u20ac\u20ac'],
    "lieu_tag": [
        'Bar', 'Restaurant', 'Cave \u00e0 manger', 'Coffee shop', 'Terrasse', 'Fast',
        'Brasserie', 'H\u00f4tel', 'Gastronomique',
    ],
    "ambiance": [
        'Entre amis', 'En famille', 'Date', 'Festif',
    ],
    "preferences_tag": [
        'Casher', '100% v\u00e9g\u00e9tarien', '"Healthy"',
    ],
}


# ── Normalization (same as Flutter SearchService._normalizeTag) ──────────────

def normalize_tag(value: str) -> str:
    """Strip accents and quotes, matching Flutter's _normalizeTag."""
    s = value
    s = s.replace('"', '')
    s = s.replace('\u00e9', 'e')   # e
    s = s.replace('\u00e8', 'e')   # e
    s = s.replace('\u00ea', 'e')   # e
    s = s.replace('\u00eb', 'e')   # e
    s = s.replace('\u00e0', 'a')   # a
    s = s.replace('\u00e2', 'a')   # a
    s = s.replace('\u00e4', 'a')   # a
    s = s.replace('\u00e7', 'c')   # c
    s = s.replace('\u00f9', 'u')   # u
    s = s.replace('\u00fb', 'u')   # u
    s = s.replace('\u00fc', 'u')   # u
    s = s.replace('\u00f4', 'o')   # o
    s = s.replace('\u00f6', 'o')   # o
    s = s.replace('\u00ee', 'i')   # i
    s = s.replace('\u00ef', 'i')   # i
    s = s.replace('\u0153', 'oe')  # oe
    s = s.replace('\u00e6', 'ae')  # ae
    return s


# ── Helpers ──────────────────────────────────────────────────────────────────

def flatten_values(val):
    """Flatten a Firestore value into a list of atomic string values."""
    if val is None:
        return []
    if isinstance(val, bool):
        return [str(val)]
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, dict):
        results = []
        for k, v in val.items():
            if v is True or v == "true":
                results.append(str(k))
            else:
                results.append(f"{k}={v}")
        return results
    return [str(val)]


def type_name(val):
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "number(int)"
    if isinstance(val, float):
        return "number(float)"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "map"
    return type(val).__name__


SEP = "=" * 90
THIN = "-" * 90


def print_header(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def print_subheader(title):
    print(f"\n{THIN}")
    print(f"  {title}")
    print(THIN)


# ── Main ─────────────────────────────────────────────────────────────────────

def audit_environment(env_name: str, cred_path: Path):
    """Run the full audit for one environment."""
    print_header(f"ENVIRONMENT: {env_name}")

    if not cred_path.exists():
        print(f"  [SKIP] Service account key not found: {cred_path}")
        return {}

    # ── Init Firebase ─────────────────────────────────────────────────────
    # Clean up any existing apps
    for app in list(firebase_admin._apps.values()):
        try:
            firebase_admin.delete_app(app)
        except Exception:
            pass

    app_name = env_name.replace(" ", "_").replace("(", "").replace(")", "")
    cred = credentials.Certificate(str(cred_path))
    app = firebase_admin.initialize_app(cred, name=app_name)
    db = firestore.client(app=app)

    # ── Fetch all restaurants ─────────────────────────────────────────────
    print(f"\n  Fetching all restaurants from '{env_name}'...")
    all_docs = list(db.collection("restaurants").stream())
    total = len(all_docs)
    print(f"  Total restaurants: {total}")

    if total == 0:
        print("  [WARN] No restaurants found — skipping.")
        firebase_admin.delete_app(app)
        return {}

    all_data = [doc.to_dict() for doc in all_docs]

    # ── Group-by for each audit field ─────────────────────────────────────
    env_results = {}  # field -> Counter

    for field in AUDIT_FIELDS:
        print_subheader(f"FIELD: {field}")

        counter = Counter()
        present = 0
        missing = 0
        sample_type = None

        for doc in all_data:
            val = doc.get(field)
            if val is not None:
                present += 1
                if sample_type is None:
                    sample_type = type_name(val)
                for fv in flatten_values(val):
                    counter[fv] += 1
            else:
                missing += 1

        env_results[field] = counter

        print(f"  Present: {present}/{total}  |  Missing: {missing}/{total}  |  Type: {sample_type or 'N/A'}")
        print(f"  Unique values: {len(counter)}")
        print()

        if counter:
            max_val_len = max(len(str(v)) for v in counter.keys())
            col_w = min(max(max_val_len + 2, 35), 60)
            print(f"  {'Value':<{col_w}} {'Count':>6}")
            print(f"  {'.' * col_w} {'.' * 6}")
            for val, cnt in counter.most_common():
                display = str(val)
                if len(display) > col_w - 2:
                    display = display[:col_w - 5] + "..."
                print(f"  {display:<{col_w}} {cnt:>6}")
        else:
            print("  (no values found)")

    # ── Cleanup ───────────────────────────────────────────────────────────
    firebase_admin.delete_app(app)
    return env_results


def print_comparison_table(env_results: dict, env_name: str):
    """Print a comparison table: Flutter UI values vs Firestore values.

    The Flutter SearchService._normalizeTag strips accents from UI values
    before comparing. But Firestore stores values WITH accents.

    So the question is: when the Flutter code normalizes 'Diner' and looks
    for it via arrayContainsAny, does it find anything? The answer is NO if
    Firestore has 'Diner' (with accents), because arrayContainsAny is exact.

    We show THREE match strategies:
      1. EXACT: UI normalized value == Firestore value (as stored)
      2. NORMALIZED: normalize(UI) == normalize(Firestore value)
      3. NONE: no match at all
    """

    print_header(f"COMPARISON TABLE: Flutter UI vs Firestore — {env_name}")
    print()
    print(f"  HOW FLUTTER SEARCH WORKS:")
    print(f"  - Flutter UI sends e.g. 'Diner' to _normalizeTag() -> 'Diner'")
    print(f"  - Then uses arrayContainsAny(['Diner']) on Firestore field")
    print(f"  - Firestore does EXACT string match (no normalization server-side)")
    print(f"  - So if Firestore stores 'Diner', the query WILL NOT find it!")
    print(f"  - _filterInMemory also normalizes UI but compares vs raw Firestore data")
    print()
    print(f"  MATCH TYPES:")
    print(f"  - EXACT    = normalized UI value found verbatim in Firestore -> works in Firestore query")
    print(f"  - NORM-OK  = normalize(Firestore) matches normalize(UI) -> works in _filterInMemory")
    print(f"  -            but FAILS in arrayContainsAny Firestore query")
    print(f"  - MISSING  = no Firestore value matches even after normalization")
    print()

    for field, ui_info in UI_VALUES.items():
        original_list = UI_ORIGINAL.get(field, [])
        firestore_counter = env_results.get(field, Counter())
        firestore_values_set = set(firestore_counter.keys())

        # Build normalized -> original Firestore value map
        firestore_norm_map = {}  # normalized -> [(original, count), ...]
        for fv in firestore_values_set:
            norm = normalize_tag(fv)
            if norm not in firestore_norm_map:
                firestore_norm_map[norm] = []
            firestore_norm_map[norm].append((fv, firestore_counter[fv]))

        print_subheader(f"{ui_info['label']}  (Firestore field: {field})")
        print()

        header = (
            f"  {'Flutter UI (original)':<28} "
            f"{'normalize(UI)':<24} "
            f"{'Firestore value (raw)':<28} "
            f"{'Count':>6}  "
            f"{'Match type':<12} "
            f"{'Works?'}"
        )
        print(header)
        print(f"  {'.' * 28} {'.' * 24} {'.' * 28} {'.' * 6}  {'.' * 12} {'.' * 20}")

        for i, norm_ui in enumerate(ui_info["values"]):
            original = original_list[i] if i < len(original_list) else norm_ui

            # Strategy 1: EXACT match (normalized UI == raw Firestore value)
            if norm_ui in firestore_values_set:
                count = firestore_counter[norm_ui]
                fs_display = norm_ui
                match_type = "EXACT"
                works = "YES (query+memory)"
            # Strategy 2: Normalized match (normalize(UI) == normalize(Firestore))
            elif norm_ui in firestore_norm_map:
                entries = firestore_norm_map[norm_ui]
                total_count = sum(c for _, c in entries)
                fs_raw_values = [fv for fv, _ in entries]
                fs_display = ", ".join(fs_raw_values)
                count = total_count
                match_type = "NORM-OK"
                works = "memory ONLY"
            else:
                count = 0
                fs_display = "(not found)"
                match_type = "!! MISSING"
                works = "NO"

            print(
                f"  {original:<28} "
                f"{norm_ui:<24} "
                f"{fs_display:<28} "
                f"{count:>6}  "
                f"{match_type:<12} "
                f"{works}"
            )

        # Show Firestore values NOT matched by any UI value
        ui_norm_set = set(v for v in ui_info["values"])
        extra_in_firestore = []
        for fv in firestore_values_set:
            norm_fv = normalize_tag(fv)
            if norm_fv not in ui_norm_set and fv not in ui_norm_set:
                extra_in_firestore.append((fv, normalize_tag(fv), firestore_counter[fv]))

        if extra_in_firestore:
            extra_in_firestore.sort(key=lambda x: -x[2])
            print()
            print(f"  ** Firestore values NOT represented in Flutter UI ({len(extra_in_firestore)}):")
            for fv, norm_fv, cnt in extra_in_firestore:
                print(f"     - {fv!r:<35} normalized={norm_fv!r:<30} count={cnt}")

        print()


def print_cross_env_summary(all_env_results: dict):
    """Print a cross-environment summary showing differences."""
    env_names = list(all_env_results.keys())
    if len(env_names) < 2:
        return

    print_header("CROSS-ENVIRONMENT COMPARISON")

    for field in AUDIT_FIELDS:
        counters = {}
        for env_name in env_names:
            counters[env_name] = all_env_results[env_name].get(field, Counter())

        all_values = set()
        for c in counters.values():
            all_values.update(c.keys())

        if not all_values:
            continue

        print_subheader(f"FIELD: {field}")

        # Short env labels
        short_labels = {}
        for en in env_names:
            if "PROD" in en:
                short_labels[en] = "PROD"
            elif "DEV" in en:
                short_labels[en] = "DEV"
            else:
                short_labels[en] = en[:10]

        max_val_len = max(len(str(v)) for v in all_values)
        col_w = min(max(max_val_len + 2, 30), 50)

        header_parts = [f"{'Value':<{col_w}}"]
        for en in env_names:
            header_parts.append(f"{short_labels[en]:>8}")
        header_parts.append("  Diff?")
        print(f"  {'  '.join(header_parts)}")
        print(f"  {'.' * (col_w + len(env_names) * 10 + 10)}")

        sorted_values = sorted(all_values, key=lambda v: -max(counters[en].get(v, 0) for en in env_names))
        for val in sorted_values:
            display = str(val)
            if len(display) > col_w - 2:
                display = display[:col_w - 5] + "..."
            parts = [f"{display:<{col_w}}"]
            counts = []
            for en in env_names:
                c = counters[en].get(val, 0)
                counts.append(c)
                parts.append(f"{c:>8}")
            diff = "  <<" if len(set(counts)) > 1 else ""
            parts.append(diff)
            print(f"  {'  '.join(parts)}")

        print()


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(SEP)
    print("  BUTTER — FULL FILTER AUDIT (Firestore restaurants collection)")
    print(f"  Environments: {', '.join(ENVS.keys())}")
    print(f"  Fields: {', '.join(AUDIT_FIELDS)}")
    print(SEP)

    all_env_results = {}

    # Run PROD first, then DEV
    for env_name, cred_path in ENVS.items():
        results = audit_environment(env_name, cred_path)
        if results:
            all_env_results[env_name] = results

    # Comparison tables (UI vs Firestore) for each env
    for env_name, results in all_env_results.items():
        print_comparison_table(results, env_name)

    # Cross-environment comparison
    if len(all_env_results) >= 2:
        print_cross_env_summary(all_env_results)

    print_header("AUDIT COMPLETE")
    print()
