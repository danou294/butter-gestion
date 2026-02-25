#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de patch direct des restaurants en Firestore DEV.
Corrige sans backup/delete/reimport :
  1. preferences_tag (colonnes Préférences dupliquées)
  2. Normalisation casse des tags (dîner→Dîner, date→Date, etc.)
  3. Stations métro multi-adresses (split par |)
  4. Arrondissements multi-adresses (split par |)
"""

import re
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# ── Config ──
EXCEL_PATH = "/Users/admin/Documents/butter_web_interface/BDD 23.02 V4 3.xlsx"
SERVICE_ACCOUNT = "/Users/admin/Documents/butter_web_interface/firebase_credentials/serviceAccountKey.dev.json"
COLLECTION = "restaurants"
BATCH_SIZE = 400

# ── Helpers (copiés d'import_restaurants.py) ──

def clean_text(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    return (s.replace("\u202f", " ")
             .replace("\u2009", " ")
             .replace("\u00a0", " ")
             .replace("–", "-")
             .replace("—", "-")
             .strip())

def arrondissement_to_code_postal(v):
    s = clean_text(v)
    if not s:
        return ""
    try:
        n = int(float(s))
        if 1 <= n <= 20:
            return f"750{n:02d}"
        if n == 116:
            return "75116"
        if 75001 <= n <= 75020 or 92000 <= n <= 95999:
            return str(n)
    except (ValueError, TypeError):
        pass
    return s

def parse_arrondissements(v):
    s = clean_text(v)
    if not s:
        return [""]
    parts = re.split(r"[|,.]", s)
    result = [arrondissement_to_code_postal(p.strip()) for p in parts if p.strip()]
    return result if result else [""]

def parse_multi_addresses(address_str):
    if not address_str:
        return [""]
    parts = [a.strip() for a in address_str.split("|") if a.strip()]
    return parts if parts else [""]

def parse_multi_coords(lat_str, lon_str):
    coords = []
    lats = [x.strip() for x in lat_str.split(";")] if lat_str else []
    lons = [x.strip() for x in lon_str.split(";")] if lon_str else []
    for i in range(max(len(lats), len(lons))):
        lat, lon = None, None
        if i < len(lats) and lats[i]:
            try: lat = float(lats[i].replace(",", "."))
            except: pass
        if i < len(lons) and lons[i]:
            try: lon = float(lons[i].replace(",", "."))
            except: pass
        coords.append((lat, lon))
    return coords

def normalize_id_from_tag(tag):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", tag).strip("-").upper()

CANONICAL_VALUES = {
    "moment": ['Petit-déjeuner', 'Brunch', 'Déjeuner', 'Goûter', 'Drinks', 'Dîner', 'Sans réservation'],
    "ambiance": ['Entre amis', 'En famille', 'Date', 'Festif'],
    "cuisine": ['Italien', 'Méditerranéen', 'Asiatique', 'Français', 'Sud-Américain', 'Américain', 'Japonais', 'Indien', 'Africain', 'Other', 'Israélien'],
    "lieu_tags": ['Bar', 'Cave à manger', 'Coffee shop', 'Terrasse', 'Fast', 'Brasserie', 'Hôtel', 'Gastronomique', 'Salle privatisable'],
}

def normalize_tag(tag, group):
    canonicals = CANONICAL_VALUES.get(group)
    if canonicals:
        for c in canonicals:
            if c.lower() == tag.lower().strip():
                return c
    return tag.rstrip('`').strip()

def collect_tags(row, group):
    column_mapping = {
        "cuisine": ['Spécialité_TAG'],
        "moment": ['Moment_TAG'],
        "lieu_tags": ['Lieu_TAG'],
        "ambiance": ['Ambiance_TAG'],
        "price_range": ['Prix_TAG'],
        "preferences": ['Préférences_TAG', 'Restrictions_TAG', 'Préférences'],
        "recommended_by": ['recommandé par - TAG'],
    }
    results = []
    for col in column_mapping.get(group, []):
        if col not in row.index:
            continue
        val = row[col]
        if isinstance(val, pd.Series):
            non_null = val.dropna()
            val = non_null.iloc[0] if len(non_null) > 0 else None
        if val is None or pd.isna(val) or str(val).strip().lower() in ["non", "", "nan"]:
            continue
        for tag in str(val).strip().split(","):
            tag = tag.strip()
            if not tag:
                continue
            if group == "preferences":
                tl = tag.lower()
                if "casher" in tl: tag = "Casher"
                elif "végétarien" in tl or "vegetarien" in tl: tag = "100% végétarien"
                elif "healthy" in tl: tag = "Healthy"
            else:
                tag = normalize_tag(tag, group)
            if tag and tag not in results:
                results.append(tag)
    return results

# ── Main ──
print("📂 Chargement Excel...")
xls = pd.ExcelFile(EXCEL_PATH)
df = xls.parse(xls.sheet_names[0])
df.columns = df.iloc[0]
rows = df.iloc[1:].copy()
print(f"📝 {len(rows)} restaurants dans l'Excel")

print("🔥 Connexion Firestore DEV...")
cred = credentials.Certificate(SERVICE_ACCOUNT)
app = firebase_admin.initialize_app(cred)
db = firestore.client()

# Construire les patches depuis l'Excel
patches = {}  # id → dict de champs à mettre à jour
updated_fields_count = {"preferences_tag": 0, "tags_normalisés": 0, "metros": 0, "arrondissements": 0}

for idx, row in rows.iterrows():
    entry = {}
    for col in df.columns:
        val = row[col]
        if isinstance(val, pd.Series):
            non_null = val.dropna()
            entry[col] = str(non_null.iloc[0]) if len(non_null) > 0 else ""
        else:
            entry[col] = str(val) if pd.notna(val) else ""

    tag = clean_text(entry.get("Ref") or entry.get("tag") or "")
    rid = normalize_id_from_tag(tag)
    if not rid:
        continue

    patch = {}

    # 1. Preferences
    prefs = collect_tags(row, "preferences")
    patch["preferences_tag"] = prefs
    patch["preferences"] = prefs

    # 2. Tags normalisés
    patch["cuisine_tag"] = collect_tags(row, "cuisine")
    patch["cuisines"] = patch["cuisine_tag"]
    patch["moment_tag"] = collect_tags(row, "moment")
    patch["moments"] = patch["moment_tag"]
    patch["lieu_tag"] = collect_tags(row, "lieu_tags")
    patch["lieux"] = patch["lieu_tag"]
    patch["location_type"] = patch["lieu_tag"]
    patch["ambiance_tag"] = collect_tags(row, "ambiance")
    patch["ambiance"] = patch["ambiance_tag"]
    patch["price_range"] = collect_tags(row, "price_range")
    patch["recommended_by_tag"] = collect_tags(row, "recommended_by")
    patch["recommended_by"] = patch["recommended_by_tag"]

    # 3. Arrondissements (split par |)
    raw_arr = clean_text(entry.get("Arrondissement") or "")
    all_arrondissements = parse_arrondissements(raw_arr)
    patch["arrondissement"] = all_arrondissements[0]
    patch["arrondissements"] = all_arrondissements

    # 4. Multi-adresses : métros + arrondissements par adresse
    raw_address = clean_text(entry.get("Adresse") or "")
    all_addresses = parse_multi_addresses(raw_address)
    num_addresses = len(all_addresses)

    raw_s1 = clean_text(entry.get("Station de metro 1") or "")
    raw_l1 = clean_text(entry.get("Lignes 1") or "")
    raw_s2 = clean_text(entry.get("Stations de metro 2 ") or "")
    raw_l2 = clean_text(entry.get("Lignes 2 ") or "")

    if num_addresses > 1:
        # Multi-adresses : splitter par |
        s1_parts = [s.strip() for s in raw_s1.split("|")] if raw_s1 else []
        l1_parts = [s.strip() for s in raw_l1.split("|")] if raw_l1 else []
        s2_parts = [s.strip() for s in raw_s2.split("|")] if raw_s2 else []
        l2_parts = [s.strip() for s in raw_l2.split("|")] if raw_l2 else []

        per_address_metros = []
        for i in range(num_addresses):
            addr_metros = []
            s1 = s1_parts[i].strip() if i < len(s1_parts) else ""
            l1 = l1_parts[i].strip() if i < len(l1_parts) else ""
            if s1 and s1.lower() not in ["non", "", "nan"]:
                addr_metros.append({"station": s1, "lines": [l.strip() for l in l1.split(",") if l.strip()] if l1 else []})
            s2 = s2_parts[i].strip() if i < len(s2_parts) else ""
            l2 = l2_parts[i].strip() if i < len(l2_parts) else ""
            if s2 and s2.lower() not in ["non", "", "nan"]:
                addr_metros.append({"station": s2, "lines": [l.strip() for l in l2.split(",") if l.strip()] if l2 else []})
            per_address_metros.append(addr_metros)

        stations_metro = per_address_metros[0] if per_address_metros else []
    else:
        stations_metro = []
        if raw_s1 and raw_s1.lower() not in ["non", "", "nan"]:
            stations_metro.append({"station": raw_s1, "lines": [l.strip() for l in raw_l1.split(",") if l.strip()] if raw_l1 else []})
        if raw_s2 and raw_s2.lower() not in ["non", "", "nan"]:
            stations_metro.append({"station": raw_s2, "lines": [l.strip() for l in raw_l2.split(",") if l.strip()] if raw_l2 else []})
        per_address_metros = [stations_metro]

    patch["stations_metro"] = stations_metro

    # Construire addresses array
    lat_str = clean_text(entry.get("Latitude") or entry.get("latitude") or "")
    lon_str = clean_text(entry.get("Longitude") or entry.get("longitude") or "")
    all_coords = parse_multi_coords(lat_str, lon_str)

    addresses_array = []
    for i in range(num_addresses):
        addresses_array.append({
            "address": all_addresses[i],
            "arrondissement": all_arrondissements[i] if i < len(all_arrondissements) else "",
            "latitude": all_coords[i][0] if i < len(all_coords) else None,
            "longitude": all_coords[i][1] if i < len(all_coords) else None,
            "stations_metro": per_address_metros[i] if i < len(per_address_metros) else [],
        })
    patch["addresses"] = addresses_array

    patches[rid] = patch

print(f"📊 {len(patches)} restaurants à patcher")

# Appliquer les patches par batch
batch_count = 0
total_updated = 0
batch = db.batch()

for rid, patch in patches.items():
    ref = db.collection(COLLECTION).document(rid)
    batch.update(ref, patch)
    batch_count += 1
    total_updated += 1

    if batch_count >= BATCH_SIZE:
        print(f"  💾 Commit batch ({total_updated}/{len(patches)})...")
        batch.commit()
        batch = db.batch()
        batch_count = 0

# Commit le dernier batch
if batch_count > 0:
    print(f"  💾 Commit batch final ({total_updated}/{len(patches)})...")
    batch.commit()

print(f"\n🎉 Patch terminé ! {total_updated} restaurants mis à jour en DEV.")
firebase_admin.delete_app(app)
