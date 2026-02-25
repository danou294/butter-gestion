#!/usr/bin/env python3
"""
Audit script for Butter Firestore `restaurants` collection (PROD: butter-vdef).
Fetches a sample of restaurants and reports field types, existence, and value distributions.
"""

import os
import sys
import json
from collections import Counter, defaultdict
from pathlib import Path

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

import firebase_admin
from firebase_admin import credentials, firestore

# ── Firebase init (PROD) ─────────────────────────────────────────────────────

SERVICE_ACCOUNT_PATH = str(
    Path(__file__).resolve().parent / "firebase_credentials" / "serviceAccountKey.prod.json"
)

if not os.path.exists(SERVICE_ACCOUNT_PATH):
    print(f"ERROR: Service account key not found at {SERVICE_ACCOUNT_PATH}")
    sys.exit(1)

cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
app = firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Fields to audit ──────────────────────────────────────────────────────────

FIELDS_TO_CHECK = [
    "price_range",
    "moment_tag",
    "moments",
    "cuisine_tag",
    "cuisines",
    "types",
    "specialite_tag",
    "lieu_tag",
    "lieux",
    "location_type",
    "ambiance",
    "preferences_tag",
    "preferences",
    "restrictions",
    "arrondissement",
    "arrondissements",
    "recommended_by_tag",
    "extras",
    "name",
    "tag",
]

# Fields for GROUP BY analysis (unique values + counts)
GROUP_BY_FIELDS = [
    "price_range",
    "moment_tag",
    "moments",
    "cuisine_tag",
    "lieu_tag",
    "lieux",
    "ambiance",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def python_type_name(val):
    """Return a human-friendly type name for a Firestore value."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "number (int)"
    if isinstance(val, float):
        return "number (float)"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "map"
    if hasattr(val, 'latitude'):  # GeoPoint
        return "geopoint"
    if hasattr(val, 'isoformat'):  # datetime
        return "timestamp"
    return type(val).__name__


def truncate(s, max_len=80):
    s = str(s)
    return s if len(s) <= max_len else s[:max_len] + "..."


def flatten_values(val):
    """Flatten a value into a list of atomic values for counting."""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, dict):
        # For maps like ambiance {key: true/false}, return keys where value is truthy
        results = []
        for k, v in val.items():
            if v is True or v == "true":
                results.append(str(k))
            else:
                results.append(f"{k}={v}")
        return results
    return [str(val)]


# ── Fetch ALL restaurants ────────────────────────────────────────────────────

print("=" * 80)
print("BUTTER FIRESTORE AUDIT — PROD (butter-vdef)")
print("Collection: restaurants")
print("=" * 80)

# First, get total count
print("\nFetching ALL restaurants from Firestore...")
all_docs = list(db.collection("restaurants").stream())
total_count = len(all_docs)
print(f"Total restaurants in collection: {total_count}")

# Use ALL documents for the group-by analysis, sample 20 for detailed field report
sample_docs = []
for doc in all_docs[:20]:
    data = doc.to_dict()
    data["__doc_id__"] = doc.id
    sample_docs.append(data)

all_data = []
for doc in all_docs:
    all_data.append(doc.to_dict())

# ── PART 1: Field-by-field audit (sample of 20) ─────────────────────────────

print("\n")
print("=" * 80)
print("PART 1: FIELD-BY-FIELD AUDIT (sample of 20 restaurants)")
print("=" * 80)

for field in FIELDS_TO_CHECK:
    print(f"\n{'─' * 70}")
    print(f"  FIELD: {field}")
    print(f"{'─' * 70}")

    exists_count = 0
    type_counter = Counter()
    sample_values = []

    for doc in sample_docs:
        if field in doc and doc[field] is not None:
            exists_count += 1
            val = doc[field]
            t = python_type_name(val)
            type_counter[t] += 1

            # Collect sample values (deduplicate)
            val_repr = truncate(repr(val), 120)
            if val_repr not in [v for v in sample_values]:
                if len(sample_values) < 5:
                    sample_values.append(val_repr)

    print(f"  Exists in: {exists_count}/{len(sample_docs)} documents")

    if exists_count == 0:
        print(f"  Type: FIELD NOT FOUND in sample")
    else:
        types_str = ", ".join(f"{t} ({c}x)" for t, c in type_counter.most_common())
        print(f"  Type(s): {types_str}")
        print(f"  Sample values ({len(sample_values)}):")
        for i, sv in enumerate(sample_values):
            print(f"    [{i+1}] {sv}")

# ── PART 2: Check ALL fields present in sample docs ─────────────────────────

print("\n\n")
print("=" * 80)
print("PART 2: ALL FIELDS FOUND IN SAMPLE (for reference)")
print("=" * 80)

all_fields_seen = Counter()
for doc in sample_docs:
    for key in doc.keys():
        if key != "__doc_id__":
            all_fields_seen[key] += 1

print(f"\n{'Field':<35} {'Count':<8} {'Type in first doc'}")
print(f"{'─' * 35} {'─' * 8} {'─' * 30}")
for field_name, count in sorted(all_fields_seen.items(), key=lambda x: x[0]):
    # Find first doc with this field to show type
    first_type = "?"
    for doc in sample_docs:
        if field_name in doc and doc[field_name] is not None:
            first_type = python_type_name(doc[field_name])
            break
    print(f"  {field_name:<33} {count:<8} {first_type}")

# ── PART 3: GROUP BY analysis (all documents) ───────────────────────────────

print("\n\n")
print("=" * 80)
print(f"PART 3: GROUP BY ANALYSIS (all {total_count} restaurants)")
print("=" * 80)

for field in GROUP_BY_FIELDS:
    print(f"\n{'─' * 70}")
    print(f"  FIELD: {field}")
    print(f"{'─' * 70}")

    value_counter = Counter()
    docs_with_field = 0
    docs_without_field = 0
    field_type_sample = None

    for doc in all_data:
        if field in doc and doc[field] is not None:
            docs_with_field += 1
            val = doc[field]
            if field_type_sample is None:
                field_type_sample = python_type_name(val)
            flat = flatten_values(val)
            for fv in flat:
                value_counter[fv] += 1
        else:
            docs_without_field += 1

    print(f"  Present in: {docs_with_field}/{total_count} documents")
    print(f"  Missing/null in: {docs_without_field}/{total_count} documents")
    if field_type_sample:
        print(f"  Typical type: {field_type_sample}")

    if value_counter:
        print(f"  Unique values: {len(value_counter)}")
        print(f"  Value distribution:")
        for val, cnt in value_counter.most_common():
            print(f"    {truncate(val, 50):.<55} {cnt:>4}")
    else:
        print(f"  NO VALUES FOUND")

# ── PART 4: Deep dive on ambiance structure ──────────────────────────────────

print("\n\n")
print("=" * 80)
print("PART 4: DEEP DIVE — ambiance field structure")
print("=" * 80)

ambiance_types = Counter()
for doc in all_data:
    if "ambiance" in doc and doc["ambiance"] is not None:
        val = doc["ambiance"]
        t = python_type_name(val)
        ambiance_types[t] += 1

print(f"\n  Type distribution: {dict(ambiance_types)}")
print(f"\n  First 3 raw ambiance values:")
shown = 0
for doc in all_data:
    if "ambiance" in doc and doc["ambiance"] is not None:
        print(f"    {json.dumps(doc['ambiance'], ensure_ascii=False, default=str)}")
        shown += 1
        if shown >= 3:
            break

# ── PART 5: Deep dive on price_range structure ──────────────────────────────

print("\n\n")
print("=" * 80)
print("PART 5: DEEP DIVE — price_range field structure")
print("=" * 80)

price_types = Counter()
for doc in all_data:
    if "price_range" in doc and doc["price_range"] is not None:
        val = doc["price_range"]
        t = python_type_name(val)
        price_types[t] += 1

print(f"\n  Type distribution: {dict(price_types)}")
print(f"\n  First 5 raw price_range values:")
shown = 0
for doc in all_data:
    if "price_range" in doc and doc["price_range"] is not None:
        print(f"    {repr(doc['price_range'])}")
        shown += 1
        if shown >= 5:
            break

# ── PART 6: Deep dive on arrondissement ──────────────────────────────────────

print("\n\n")
print("=" * 80)
print("PART 6: DEEP DIVE — arrondissement field structure")
print("=" * 80)

arr_types = Counter()
for doc in all_data:
    if "arrondissement" in doc and doc["arrondissement"] is not None:
        val = doc["arrondissement"]
        t = python_type_name(val)
        arr_types[t] += 1

print(f"\n  Type distribution: {dict(arr_types)}")
print(f"\n  All unique arrondissement values:")
arr_values = Counter()
for doc in all_data:
    if "arrondissement" in doc and doc["arrondissement"] is not None:
        arr_values[str(doc["arrondissement"])] += 1
for val, cnt in arr_values.most_common():
    print(f"    {val:.<40} {cnt:>4}")


print("\n\n")
print("=" * 80)
print("AUDIT COMPLETE")
print("=" * 80)
