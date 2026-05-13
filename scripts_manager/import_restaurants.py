#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script d'import end-to-end pour la collection 'restaurants' dans Firebase Firestore
Adapté pour Django
"""

import os
import re
import ast
import csv
import json
import sys
import hashlib
import pathlib
import traceback
import datetime
import time
import urllib.parse
import urllib.request
from collections import defaultdict, Counter
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

# Import de la config Django
from config import FIRESTORE_COLLECTION, INPUT_DIR, EXPORTS_DIR, BACKUP_DIR

# -------------------- Config --------------------
COLLECTION_SOURCE = FIRESTORE_COLLECTION
COLLECTION_IMPORT_LOGS = "import logs"
BATCH_SIZE = 400
DEDUPE_IDS = False

# -------------------- Marrakech Column Mappings --------------------
# Mapping colonnes Excel Marrakech → colonnes attendues par le script (format Paris)
MARRAKECH_COLUMN_MAPPINGS = {
    "Restaurants": {
        # Alias possibles pour le nom (la 1re trouvée dans l'Excel gagne)
        "Restaurant": "Vrai Nom",
        "Nom": "Vrai Nom",
        "Spécialité précise": "Spécialité_TAG",
        "Quartier": "Arrondissement",
        "Instagram": "Lien de votre compte instagram",
        "Menu": "Lien Menu",
        "Moments": "Moment_TAG",
        "Horaires d'ouverture": "Horaires",
        "Tranche de prix": "Prix_TAG",
        "Commentaire": "Infos",
    },
    "Hôtels": {
        # Alias possibles pour le nom
        "Hôtel / Établissement": "Vrai Nom",
        "Nom de l'hôtel": "Vrai Nom",
        "Nom": "Vrai Nom",
        "Prix moyen": "Prix par nuit",
        "Quartier": "Arrondissement",
        "Catégorie": "Catégorie hôtel",
        "Instagram": "Lien de votre compte instagram",
        "Description": "Infos",
    },
    "Daypass": {
        "Nom": "Vrai Nom",
        "Tag": "Ref",
        "Quartier": "Arrondissement",
        "Instagram": "Lien de votre compte instagram",
        "Tranche de prix": "Prix_TAG",
        "Lien réservation": "Lien de réservation",
        "Notes": "Infos",
    },
}

# Venue type automatique par nom d'onglet Excel
SHEET_VENUE_TYPE = {
    "Restaurants": "restaurant",
    "Hôtels": "hotel",
    "Daypass": "daypass",
}

# Mapping prix $ → € (Marrakech utilise $ dans l'Excel)
DOLLAR_TO_EURO_PRICE = {
    "$": "€",
    "$$": "€€",
    "$$$": "€€€",
    "$$$$": "€€€€",
}

# -------------------- Utilities --------------------
def ensure_dir(p: str):
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

def now_paris_str() -> str:
    dt = datetime.datetime.now(datetime.timezone.utc)
    if ZoneInfo is not None:
        local = dt.astimezone(ZoneInfo("Europe/Paris"))
        return local.strftime("%d %b %Y à %H:%M:%S %Z%z")
    else:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def log(msg: str, log_file: str):
    print(msg)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def init_firestore(log_file: str, request=None):
    """
    Initialise Firestore avec le bon environnement.
    Gère le changement d'environnement en recréant l'app si nécessaire.

    Args:
        log_file: Chemin du fichier de log
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Déterminer l'environnement cible et le chemin du service account
    try:
        from scripts_manager.firebase_utils import get_service_account_path, get_firebase_env_from_session
        sa = get_service_account_path(request)
        target_env = get_firebase_env_from_session(request)
    except ImportError:
        # Fallback si firebase_utils n'est pas disponible
        from config import SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD
        target_env = os.getenv('FIREBASE_ENV', 'prod').lower()
        if target_env == 'dev':
            sa = SERVICE_ACCOUNT_PATH_DEV
        else:
            sa = SERVICE_ACCOUNT_PATH_PROD

    if not os.path.exists(sa):
        log(f"❌ Service account introuvable: {sa}", log_file)
        raise FileNotFoundError(f"Service account introuvable: {sa}")

    log(f"🔑 Environnement: {target_env.upper()} — Service account: {sa}", log_file)

    # Si une app existe déjà pour un autre environnement, la supprimer
    if firebase_admin._apps:
        existing_app = firebase_admin.get_app()
        existing_project = existing_app.project_id
        cred = credentials.Certificate(sa)
        target_project = cred.project_id
        if existing_project != target_project:
            log(f"🔄 Changement d'environnement détecté: {existing_project} -> {target_project}. Réinitialisation.", log_file)
            firebase_admin.delete_app(existing_app)
            firebase_admin.initialize_app(cred)
        # Sinon, l'app existante est déjà pour le bon projet
    else:
        cred = credentials.Certificate(sa)
        firebase_admin.initialize_app(cred)

    return firestore.client()

def clean_text(s):
    """Nettoie le texte d'une cellule Excel"""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    return (s.replace("\u202f", " ")
             .replace("\u2009", " ")
             .replace(" ", " ")
             .replace("\xa0", " ")
             .replace("–", "-")
             .replace("—", "-")
             .strip())

def geocode_address(address: str, log_file: str = None, max_retries: int = 3, restaurant_name: str = None, city: str = "Paris") -> Optional[Tuple[float, float]]:
    """Géocode une adresse en utilisant Nominatim (OpenStreetMap) avec système de retry."""
    if not address or not address.strip():
        if log_file:
            log(f"⚠️  Géocodage: adresse vide ou None", log_file)
        return None

    address_clean = clean_text(address)
    if not address_clean:
        if log_file:
            log(f"⚠️  Géocodage: adresse nettoyée vide", log_file)
        return None

    # Ajouter la ville si nécessaire
    original_address = address_clean
    city_lower = city.lower() if city else "paris"
    if city_lower not in address_clean.lower():
        country = "Maroc" if city_lower == "marrakech" else "France"
        address_clean = f"{address_clean}, {city}, {country}"
        if log_file:
            log(f"🌍 [{restaurant_name or 'Restaurant'}] Adresse enrichie: '{original_address}' → '{address_clean}'", log_file)
    
    encoded_address = urllib.parse.quote(address_clean)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_address}&format=json&limit=1&addressdetails=1"
    
    if log_file:
        log(f"🌐 [{restaurant_name or 'Restaurant'}] Appel API Nominatim pour: '{address_clean}'", log_file)
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                wait_time = min(2 ** (attempt - 1), 10)
                if log_file:
                    log(f"🔄 [{restaurant_name or 'Restaurant'}] Géocodage: tentative {attempt}/{max_retries} pour '{address_clean[:60]}...' (attente {wait_time}s)", log_file)
                time.sleep(wait_time)
            else:
                if log_file:
                    log(f"🔄 [{restaurant_name or 'Restaurant'}] Géocodage: tentative {attempt}/{max_retries} pour '{address_clean[:60]}...'", log_file)
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'RestaurantImportScript/1.0')
            req.add_header('Accept', 'application/json')
            
            if log_file:
                log(f"📡 [{restaurant_name or 'Restaurant'}] Envoi requête HTTP à Nominatim...", log_file)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                response_data = response.read()
                if log_file:
                    log(f"📥 [{restaurant_name or 'Restaurant'}] Réponse reçue ({len(response_data)} bytes)", log_file)
                
                data = json.loads(response_data.decode())
                
                if data and len(data) > 0:
                    result = data[0]
                    lat = float(result.get('lat', 0))
                    lon = float(result.get('lon', 0))
                    
                    if log_file:
                        log(f"📍 [{restaurant_name or 'Restaurant'}] Coordonnées brutes de l'API: lat={lat}, lon={lon}", log_file)
                    
                    if lat != 0 and lon != 0:
                        if log_file:
                            log(f"✅ [{restaurant_name or 'Restaurant'}] Géocodage réussi: '{address_clean[:60]}...' → ({lat:.6f}, {lon:.6f})", log_file)
                        return (lat, lon)
                    else:
                        if log_file:
                            log(f"⚠️  [{restaurant_name or 'Restaurant'}] Coordonnées invalides (0,0) reçues de l'API", log_file)
                else:
                    if log_file:
                        log(f"⚠️  [{restaurant_name or 'Restaurant'}] Aucun résultat dans la réponse de l'API", log_file)
            
            if attempt == max_retries and log_file:
                log(f"❌ [{restaurant_name or 'Restaurant'}] Géocodage échoué après {max_retries} tentatives: '{address_clean[:60]}...' (aucun résultat valide)", log_file)
            
        except urllib.error.URLError as e:
            if log_file:
                log(f"❌ [{restaurant_name or 'Restaurant'}] Erreur réseau lors du géocodage (tentative {attempt}/{max_retries}): {type(e).__name__} - {str(e)[:100]}", log_file)
            if attempt == max_retries:
                if log_file:
                    log(f"❌ [{restaurant_name or 'Restaurant'}] Géocodage définitivement échoué: erreur réseau", log_file)
            continue
        except Exception as e:
            if log_file:
                log(f"❌ [{restaurant_name or 'Restaurant'}] Erreur inattendue lors du géocodage (tentative {attempt}/{max_retries}): {type(e).__name__} - {str(e)[:100]}", log_file)
            if attempt == max_retries:
                if log_file:
                    log(f"❌ [{restaurant_name or 'Restaurant'}] Géocodage définitivement échoué: {type(e).__name__}", log_file)
            continue
    
    return None

# -------------------- Backup --------------------
def export_collection(db, collection_name: str, out_dir: str, log_file: str, city: str = None) -> Dict[str, Any]:
    ensure_dir(out_dir)
    suffix = f"_{city.lower()}" if city else ""
    json_path = os.path.join(out_dir, f"{collection_name}{suffix}.json")
    ndjson_path = os.path.join(out_dir, f"{collection_name}{suffix}.ndjson")
    csv_path = os.path.join(out_dir, f"{collection_name}{suffix}.csv")
    meta_path = os.path.join(out_dir, "backup_meta.json")

    query = db.collection(collection_name)
    if city:
        query = query.where("city", "==", city)
    docs = list(query.stream())
    count = len(docs)
    data_array = []

    with open(ndjson_path, "w", encoding="utf-8") as nf:
        for d in docs:
            obj = d.to_dict() or {}
            row = {"id": d.id, **obj}
            data_array.append(row)
            nf.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(data_array, jf, ensure_ascii=False, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=["id", "name", "address", "arrondissement", "tag"])
        writer.writeheader()
        for r in data_array:
            writer.writerow({
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "address": r.get("address", ""),
                "arrondissement": r.get("arrondissement", ""),
                "tag": r.get("tag", ""),
            })

    meta = {
        "collection": collection_name,
        "count": count,
        "json": os.path.basename(json_path),
        "ndjson": os.path.basename(ndjson_path),
        "csv": os.path.basename(csv_path),
        "timestamp": now_paris_str(),
        "sha256_json": sha256_file(json_path),
        "sha256_ndjson": sha256_file(ndjson_path),
    }
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)

    log(f"✅ Backup OK ({count} docs) → {out_dir}", log_file)
    return {"count": count, "dir": out_dir, **meta}

# -------------------- Excel → records --------------------
def to_list(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = clean_text(v)
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            items = ast.literal_eval(s)
            if isinstance(items, (list, tuple)):
                return [str(x).strip() for x in items if str(x).strip()]
        except Exception:
            pass
    parts = re.split(r"[,/;|·]", s)
    return [p.strip() for p in parts if p.strip()]

def string_to_tag_list(v):
    """Convertit une string de tags séparés par des virgules en liste de tags nettoyés"""
    if not v or (isinstance(v, float) and pd.isna(v)):
        return []
    s = clean_text(v)
    if not s or s.lower() in ["non", "nan", ""]:
        return []
    tags = [tag.strip() for tag in s.split(",") if tag.strip()]
    return [tag for tag in tags if tag.lower() not in ["non", "nan", ""]]

DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DAY_EN_TO_FR = dict(zip(DAYS_EN, DAYS_FR))
DAY_PATTERN = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)\s*:\s*"
RE_12H = re.compile(r"(\d{1,2}:\d{2})\s*([APMapm]{2})?\s*-\s*(\d{1,2}:\d{2})\s*([APMapm]{2})")
RE_24H = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")

def to_24h_safe(hour_str, suffix=""):
    s = hour_str.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", s) and not suffix:
        return s
    try:
        return datetime.datetime.strptime(f"{s} {suffix}".strip(), "%I:%M %p").strftime("%H:%M")
    except Exception:
        return s

def parse_bracketed_list_if_any(hours_str):
    t = clean_text(hours_str)
    if t.startswith("[") and t.endswith("]"):
        try:
            items = ast.literal_eval(t)
            if isinstance(items, (list, tuple)):
                return "\n".join(str(x).strip() for x in items if str(x).strip())
        except Exception:
            return t
    return t

def extract_slot_range(slot):
    slot = clean_text(slot)
    m12 = RE_12H.search(slot)
    if m12:
        h1, s1, h2, s2 = m12.groups()
        s1 = s1 or s2
        return f"{to_24h_safe(h1, s1)} - {to_24h_safe(h2, s2)}"
    m24 = RE_24H.search(slot)
    if m24:
        h1, h2 = m24.groups()
        return f"{to_24h_safe(h1)} - {to_24h_safe(h2)}"
    return None

def parse_day_slots(text):
    text = clean_text(text)
    if not text or re.search(r"\b(closed|ferm[ée]?)\b", text, flags=re.I):
        return {"closed": True}
    slots = [s.strip() for s in re.split(r"[;,]", text) if s.strip()]
    result = {}
    idx = 1
    for s in slots:
        rng = extract_slot_range(s)
        if rng:
            result[f"service_{idx}"] = rng
            idx += 1
    return result if result else {"closed": True}

def split_hours_by_day(hours_str):
    text = parse_bracketed_list_if_any(hours_str)
    # Case-insensitive : accepte "lundi", "Lundi", "LUNDI", etc.
    text = re.sub(DAY_PATTERN, r"\n\1: ", clean_text(text), flags=re.IGNORECASE)
    parts = re.split(DAY_PATTERN, text, flags=re.IGNORECASE)
    chunks = {}
    for i in range(1, len(parts), 2):
        # Normaliser la casse : "lundi" → "Lundi" pour matcher DAY_EN_TO_FR / DAYS_FR
        day = parts[i].capitalize()
        value = parts[i + 1].strip()
        fr_day = DAY_EN_TO_FR.get(day, day)
        chunks[fr_day] = value
    return chunks

def process_hours(hours_str):
    if not clean_text(hours_str):
        return {}
    day_blocks = split_hours_by_day(hours_str)
    structured = {fr_day: parse_day_slots(value) for fr_day, value in day_blocks.items()}
    for d in DAYS_FR:
        structured.setdefault(d, {"closed": True})
    return structured

def arrondissement_to_code_postal(v):
    """Convertit la valeur d'arrondissement en code postal complet"""
    s = clean_text(v)
    if not s:
        return ""
    if re.match(r"^\d{5}$", s):
        return s
    try:
        n = int(s)
        if 1 <= n <= 20:
            return f"750{n:02d}"
    except Exception:
        pass
    return s

def parse_arrondissements(v):
    """Parse un champ arrondissement multi-valeurs (séparés par |, , ou .) en liste de codes postaux."""
    s = clean_text(v)
    if not s:
        return [""]
    # Split par | (multi-adresses) puis par , ou . (multi-arrondissements par adresse)
    parts = re.split(r"[|,.]", s)
    result = [arrondissement_to_code_postal(p.strip()) for p in parts if p.strip()]
    return result if result else [""]

def parse_multi_addresses(address_str):
    """Parse un champ adresse multi-valeurs (séparés par |) en liste d'adresses."""
    if not address_str:
        return [""]
    parts = [a.strip() for a in address_str.split("|") if a.strip()]
    return parts if parts else [""]

def parse_multi_coords(lat_str, lon_str):
    """Parse des coordonnées multi-valeurs (séparées par ;) en liste de tuples (lat, lng)."""
    coords = []
    lats = [x.strip() for x in lat_str.split(";")] if lat_str else []
    lons = [x.strip() for x in lon_str.split(";")] if lon_str else []
    max_len = max(len(lats), len(lons))
    for i in range(max_len):
        lat = None
        lon = None
        if i < len(lats) and lats[i]:
            try:
                lat = float(lats[i].replace(",", "."))
            except (ValueError, AttributeError):
                lat = None
        if i < len(lons) and lons[i]:
            try:
                lon = float(lons[i].replace(",", "."))
            except (ValueError, AttributeError):
                lon = None
        coords.append((lat, lon))
    return coords

def normalize_id_from_tag(tag):
    rid = re.sub(r"[^a-zA-Z0-9_-]+", "-", tag).strip("-").upper()
    return rid

def _generate_ref_from_name(name):
    """Génère un Ref/tag depuis le nom du restaurant quand pas de colonne Ref.
    Exemple: 'Dardar Rooftop' → 'dardar-rooftop'
    normalize_id_from_tag() convertira ensuite en 'DARDAR-ROOFTOP' pour l'ID Firestore.
    """
    import unicodedata
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = clean_text(str(name)).lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s

TAG_GROUPS = {
    "type_tags": ['Restaurant', 'Restaurant haut de gamme', 'Restaurant gastronomique', 'Restaurant étoilé',
                         'Brasserie', 'Cave à manger', 'Fast',
                         'Boulangerie/pâtisserie', 'Concept brunch', 'Concept goûter',
                         'Coffee shop/salon de thé', 'Bar'],
    "moment": ['Petit-déjeuner', 'Brunch', 'Déjeuner', 'Goûter', 'Apéro', 'Dîner', 'Drinks', 'Sans réservation'],
    "location_type": ['Rue', 'Bar', 'Brasserie', 'Cave à manger', 'Restaurant', 'Fast', 'Hotel', 'Étoilé', 'Coffee Shop', 'Salle privatisable', 'Terrasse'],
    "location_name": [],
    "lieu_tags": ['Rue', 'Bar', 'Brasserie', 'Cave à manger', 'Restaurant', 'Fast', 'Hotel', 'Hôtel', 'Étoilé', 'Coffee Shop', 'Salle privatisable', 'Terrasse', 'Rooftop'],
    "ambiance": ['Entre amis', 'En famille', 'Date', 'Festif'],
    "price_range": ['€', '€€', '€€€', '€€€€'],
    "cuisine": ['Africain', 'Américain', 'Asiatique', 'Chinois', 'Coréen', 'Colombien', 'Français', 'Fusion',
                 'Grec', 'Healthy', 'Indien', 'International', 'Israélien', 'Italien', 'Japonais',
                 'Libanais', 'Marocain', 'Mexicain', 'Méditerranéen', 'Oriental', 'Péruvien',
                 'Sud-Américain', 'Thaï', 'Végétarien', 'Vietnamien'],
    "preferences": ['Casher', '100% végétarien', 'Healthy'],
    "terrace": ['Terrasse', 'Terrasse classique', 'Cour', 'Rooftop'],
    "recommended_by": []  # Pas de valeurs prédéfinies, ce sont des tags libres
}

def collect_type_tags_from_columns(row):
    """Collecte des tags de type depuis les colonnes _TAG appropriées"""
    try:
        type_tags = []
        for col in ['Spécialité_TAG', 'Lieu_TAG', 'Ambiance_TAG']:
            if col in row.index:
                val = row[col]
                if pd.notna(val) and str(val).strip().lower() not in ["non", "", "nan"]:
                    type_tags.append(str(val).strip())
        return ", ".join(type_tags)
    except Exception as e:
        return ""

def collect_location_name_from_columns(row):
    """Collecte du nom du lieu depuis les colonnes _AFFICHAGE appropriées"""
    try:
        location_names = []
        for col in ['Lieu_AFFICHAGE', 'Ambiance_AFFICHAGE']:
            if col in row.index:
                val = row[col]
                if pd.notna(val) and str(val).strip().lower() not in ["non", "", "nan"]:
                    location_names.append(str(val).strip())
        return ", ".join(location_names)
    except Exception as e:
        return ""

def _normalize_tag_case(tag, tag_group_name):
    """Normalise la casse des tags pour correspondre aux valeurs attendues par Flutter.
    Corrige les incohérences comme 'dîner' → 'Dîner', 'date' → 'Date', 'Sud-américain' → 'Sud-Américain'
    """
    # Mapping des valeurs canoniques par groupe de tags
    canonical_values = {
        "moment": ['Petit-déjeuner', 'Brunch', 'Déjeuner', 'Goûter', 'Drinks', 'Dîner', 'Sans réservation'],
        "ambiance": ['Entre amis', 'En famille', 'Date', 'Festif'],
        "cuisine": ['Italien', 'Méditerranéen', 'Asiatique', 'Français', 'Sud-Américain', 'Américain', 'Japonais', 'Indien', 'Africain', 'Other', 'Israélien'],
        "lieu_tags": ['Bar', 'Cave à manger', 'Coffee shop', 'Terrasse', 'Fast', 'Brasserie', 'Hôtel', 'Gastronomique', 'Salle privatisable'],
        "location_type": ['Bar', 'Cave à manger', 'Coffee shop', 'Terrasse', 'Fast', 'Brasserie', 'Hôtel', 'Gastronomique', 'Salle privatisable'],
    }
    group_canonicals = canonical_values.get(tag_group_name)
    if group_canonicals:
        tag_lower = tag.lower().strip()
        for canonical in group_canonicals:
            if canonical.lower() == tag_lower:
                return canonical
    return tag

def collect_tags_from_excel_columns(row, tag_group_name):
    """Collecte des tags depuis les colonnes Excel _TAG et _AFFICHAGE"""
    try:
        results = []
        column_mapping = {
            "type_tags": ['Spécialité_TAG'],
            "moment": ['Moment_TAG'],
            "location_type": ['Lieu_TAG'],
            "lieu_tags": ['Lieu_TAG'],
            "ambiance": ['Ambiance_TAG'],
            "price_range": ['Prix_TAG'],
            "cuisine": ['Spécialité_TAG'],
            "preferences": ['Préférences_TAG', 'Restrictions_TAG', 'Préférences'],  # Support ancien et nouveau nom, et format sans _TAG
            "terrace": ['Lieu_TAG', 'Ambiance_TAG'],
            "recommended_by": ['recommandé par - TAG']
        }
        columns_to_check = column_mapping.get(tag_group_name, [])
        for col in columns_to_check:
            if col in row.index:
                val = row[col]
                # Gérer les colonnes dupliquées (ex: 2x "Préférences") → pandas retourne une Series
                if isinstance(val, pd.Series):
                    non_null = val.dropna()
                    if len(non_null) > 0:
                        val = non_null.iloc[0]
                    else:
                        continue
                if pd.notna(val) and str(val).strip().lower() not in ["non", "", "nan"]:
                    val_str = str(val).strip()
                    tags = [tag.strip() for tag in val_str.split(",") if tag.strip()]
                    for tag in tags:
                        if tag_group_name == "terrace":
                            if "terrasse" in tag.lower() or "rooftop" in tag.lower() or "cour" in tag.lower():
                                if tag not in results:
                                    results.append(tag)
                        elif tag_group_name == "preferences":
                            # Normalisation des préférences
                            tag_lower = tag.lower().strip()
                            if "casher" in tag_lower:
                                clean_tag = "Casher"
                            elif "végétarien" in tag_lower or "vegetarien" in tag_lower:
                                clean_tag = "100% végétarien"
                            elif "healthy" in tag_lower:
                                clean_tag = "Healthy"
                            else:
                                # Garder la valeur telle quelle si elle correspond aux nouvelles valeurs
                                clean_tag = tag
                            if clean_tag not in results:
                                results.append(clean_tag)
                        elif tag_group_name == "recommended_by":
                            # Tags libres pour "recommandé par"
                            if tag not in results:
                                results.append(tag)
                        else:
                            # Normalisation de la casse pour éviter les doublons (ex: "dîner" → "Dîner", "date" → "Date")
                            normalized_tag = _normalize_tag_case(tag, tag_group_name)
                            # Nettoyer les caractères parasites (ex: backtick final)
                            normalized_tag = normalized_tag.rstrip('`').strip()
                            if normalized_tag and normalized_tag not in results:
                                results.append(normalized_tag)
        return results
    except Exception as e:
        return []

def collect_affichage_tags(row):
    """Collecte tous les tags d'affichage (sauf spécialité) et retourne une liste"""
    affichage_parts = []
    affichage_columns = [
        "Moment_AFFICHAGE",
        "Ambiance_AFFICHAGE", 
        "Lieu_AFFICHAGE",
        "Préférences_AFFICHAGE",
        "Restrictions_AFFICHAGE",  # Support ancien nom pour compatibilité
        "recommandé par - AFFICHAGE"
    ]
    for col in affichage_columns:
        if col in row.index:
            val = row[col]
            # Gérer les colonnes dupliquées → pandas retourne une Series
            if isinstance(val, pd.Series):
                non_null = val.dropna()
                if len(non_null) > 0:
                    val = non_null.iloc[0]
                else:
                    continue
            value = str(val).strip()
            if value and value.lower() not in ["", "nan", "non"]:
                items = [item.strip() for item in value.split(",") if item.strip()]
                for item in items:
                    if item not in affichage_parts:
                        affichage_parts.append(item)
    return affichage_parts

def collect_specialite_affichage(row):
    """Collecte uniquement Spécialité_AFFICHAGE"""
    if "Spécialité_AFFICHAGE" in row.index:
        value = str(row["Spécialité_AFFICHAGE"]).strip()
        if value and value.lower() not in ["", "nan", "non"]:
            return value
    return ""

# -------------------- Normalisation Marrakech --------------------

def _synthesize_restaurant_tags(df, rows, log_file):
    """Synthétise les colonnes TAG depuis les champs booléens de l'onglet Restaurants Marrakech."""
    # Rooftop ? / Dans un hôtel ? → Lieu_TAG
    if "Rooftop ?" in rows.columns or "Dans un hôtel ?" in rows.columns:
        def _build_lieu_tag(row):
            parts = []
            rooftop = str(row.get("Rooftop ?", "")).strip().lower()
            if rooftop == "oui":
                parts.append("Rooftop")
            hotel = str(row.get("Dans un hôtel ?", "")).strip().lower()
            if hotel == "oui":
                parts.append("Hôtel")
            return ", ".join(parts)
        rows["Lieu_TAG"] = rows.apply(_build_lieu_tag, axis=1)
        log(f"   Lieu_TAG synthétisé depuis Rooftop/Hôtel", log_file)

    # Festif ? → Ambiance_TAG
    if "Festif ?" in rows.columns:
        def _build_ambiance_tag(row):
            festif = str(row.get("Festif ?", "")).strip().lower()
            return "Festif" if festif == "oui" else ""
        rows["Ambiance_TAG"] = rows.apply(_build_ambiance_tag, axis=1)
        log(f"   Ambiance_TAG synthétisé depuis Festif", log_file)

    # Nom de l'hôtel → enrichit Infos (description du resto)
    if "Nom de l'hôtel" in rows.columns:
        def _enrich_infos_with_hotel_name(row):
            parts = []
            existing = str(row.get("Infos", "")).strip()
            if existing and existing.lower() not in ["", "nan"]:
                parts.append(existing)
            hotel_name = str(row.get("Nom de l'hôtel", "")).strip()
            if hotel_name and hotel_name.lower() not in ["", "nan"]:
                parts.append(f"Situé dans l'hôtel {hotel_name}")
            return " | ".join(parts)
        rows["Infos"] = rows.apply(_enrich_infos_with_hotel_name, axis=1)
        log(f"   Nom de l'hôtel intégré dans Infos", log_file)

    # Prix $ → €
    if "Prix_TAG" in rows.columns:
        rows["Prix_TAG"] = rows["Prix_TAG"].apply(
            lambda x: DOLLAR_TO_EURO_PRICE.get(str(x).strip(), str(x).strip()) if pd.notna(x) else ""
        )


def _synthesize_hotel_fields(df, rows, log_file):
    """Synthétise les champs pour l'onglet Hôtels Marrakech."""
    # Combiner colonnes booléennes d'équipements → Équipements
    equipment_cols = {"Piscine": "Piscine", "Spa": "Spa", "Restaurant": "Restaurant", "Salle de sport": "Salle de sport"}
    available = [c for c in equipment_cols if c in rows.columns]
    if available:
        def _build_equipements(row):
            equips = []
            for col, label in equipment_cols.items():
                if str(row.get(col, "")).strip().lower() == "oui":
                    equips.append(label)
            return ", ".join(equips)
        rows["Équipements"] = rows.apply(_build_equipements, axis=1)
        log(f"   Équipements synthétisés depuis: {available}", log_file)

    # Fourchette + Note Google → Infos
    extras = []
    if "Fourchette (Basse / Haute saison)" in rows.columns:
        extras.append(("Fourchette (Basse / Haute saison)", "Fourchette"))
    if "Note Google" in rows.columns:
        extras.append(("Note Google", "Note Google"))
    if extras:
        def _enrich_infos(row):
            parts = []
            existing = str(row.get("Infos", "")).strip()
            if existing and existing.lower() not in ["", "nan"]:
                parts.append(existing)
            for col, label in extras:
                val = str(row.get(col, "")).strip()
                if val and val.lower() not in ["", "nan"]:
                    parts.append(f"{label}: {val}")
            return " | ".join(parts)
        rows["Infos"] = rows.apply(_enrich_infos, axis=1)


def _synthesize_daypass_fields(df, rows, log_file):
    """Synthétise les champs pour l'onglet Daypass Marrakech."""
    # Formules et prix → Infos
    if "Formules et prix" in rows.columns:
        def _enrich_infos(row):
            parts = []
            existing = str(row.get("Infos", "")).strip()
            if existing and existing.lower() not in ["", "nan"]:
                parts.append(existing)
            formules = str(row.get("Formules et prix", "")).strip()
            if formules and formules.lower() not in ["", "nan"]:
                parts.append(f"Formules: {formules}")
            return " | ".join(parts)
        rows["Infos"] = rows.apply(_enrich_infos, axis=1)
        log(f"   Formules et prix intégrés dans Infos", log_file)

    # Prix numérique MAD → tranche €
    if "Prix_TAG" in rows.columns:
        def _normalize_daypass_price(val):
            s = str(val).strip() if pd.notna(val) else ""
            if not s or s.lower() == "nan":
                return ""
            if "€" in s or "$" in s:
                return DOLLAR_TO_EURO_PRICE.get(s, s)
            try:
                amount = float(s.replace(",", ".").replace(" ", ""))
                if amount < 300:
                    return "€"
                elif amount < 600:
                    return "€€"
                elif amount < 1000:
                    return "€€€"
                else:
                    return "€€€€"
            except (ValueError, TypeError):
                return s
        rows["Prix_TAG"] = rows["Prix_TAG"].apply(_normalize_daypass_price)
        log(f"   Prix Daypass normalisés (MAD → tranches €)", log_file)


def _normalize_marrakech_columns(df, rows, sheet_name, import_city, log_file):
    """
    Normalise les colonnes d'un Excel non-Paris (Marrakech) pour matcher le format attendu.
    Appelée AVANT row_to_flat_doc() pour que le traitement existant fonctionne tel quel.
    """
    log(f"🏙️  Normalisation colonnes {import_city} (feuille: {sheet_name})...", log_file)

    # 0) Strip whitespace autour des noms de colonnes (robustesse aux espaces parasites)
    strip_rename = {c: c.strip() for c in df.columns if isinstance(c, str) and c != c.strip()}
    if strip_rename:
        df = df.rename(columns=strip_rename)
        rows = rows.rename(columns=strip_rename)
        log(f"   Espaces nettoyés sur colonnes: {list(strip_rename.keys())}", log_file)

    mapping = MARRAKECH_COLUMN_MAPPINGS.get(sheet_name, {})
    if not mapping:
        log(f"   ⚠️  Pas de mapping pour la feuille '{sheet_name}', tentative avec Restaurants", log_file)
        mapping = MARRAKECH_COLUMN_MAPPINGS.get("Restaurants", {})

    # 1) Renommer les colonnes — support alias multiples (1re source trouvée gagne par dst)
    rename_dict = {}
    seen_dst = set(df.columns)  # ne pas écraser une colonne déjà existante
    for src_col, dst_col in mapping.items():
        if src_col not in df.columns or src_col == dst_col:
            continue
        if dst_col in seen_dst:
            log(f"   ⚠️  Alias '{src_col}' ignoré : '{dst_col}' déjà présent", log_file)
            continue
        rename_dict[src_col] = dst_col
        seen_dst.add(dst_col)
    if rename_dict:
        df = df.rename(columns=rename_dict)
        rows = rows.rename(columns=rename_dict)
        log(f"   Colonnes renommées: {list(rename_dict.keys())} → {list(rename_dict.values())}", log_file)

    # 2) Copier TAG → AFFICHAGE pour les champs qui n'ont pas de colonne _AFFICHAGE
    for tag_col, aff_col in [("Spécialité_TAG", "Spécialité_AFFICHAGE"), ("Moment_TAG", "Moment_AFFICHAGE")]:
        if tag_col in df.columns and aff_col not in df.columns:
            df[aff_col] = df[tag_col]
            rows[aff_col] = rows[tag_col]

    # 3) Auto-set venue_type depuis le nom d'onglet
    venue_type = SHEET_VENUE_TYPE.get(sheet_name, "restaurant")
    df["Type de lieu"] = venue_type
    rows["Type de lieu"] = venue_type
    log(f"   venue_type auto: '{venue_type}'", log_file)

    # 4) Auto-set ville
    df["Ville"] = import_city
    rows["Ville"] = import_city

    # 5) Auto-générer Ref depuis le nom quand absent
    if "Ref" not in df.columns and "tag" not in df.columns:
        name_col = "Vrai Nom" if "Vrai Nom" in df.columns else None
        if name_col:
            df["Ref"] = df[name_col].apply(lambda x: _generate_ref_from_name(x) if pd.notna(x) else "")
            rows["Ref"] = rows[name_col].apply(lambda x: _generate_ref_from_name(x) if pd.notna(x) else "")
            log(f"   Ref auto-généré depuis '{name_col}' pour {len(rows)} lignes", log_file)

    # 6) Aussi copier Vrai Nom → Nom de base si absent
    if "Vrai Nom" in df.columns and "Nom de base" not in df.columns:
        df["Nom de base"] = df["Vrai Nom"]
        rows["Nom de base"] = rows["Vrai Nom"]

    # 7) Synthèse spécifique par onglet
    if sheet_name == "Restaurants":
        _synthesize_restaurant_tags(df, rows, log_file)
    elif sheet_name == "Hôtels":
        _synthesize_hotel_fields(df, rows, log_file)
    elif sheet_name == "Daypass":
        _synthesize_daypass_fields(df, rows, log_file)

    # 8) Synchroniser df.columns avec rows.columns (row_to_flat_doc itère sur df.columns)
    for col in rows.columns:
        if col not in df.columns:
            df[col] = ""

    # 9) Supprimer les lignes vides (Hôtels a 918 rows mais ~31 avec données)
    if "Vrai Nom" in rows.columns:
        before = len(rows)
        rows = rows.dropna(subset=["Vrai Nom"])
        rows = rows[rows["Vrai Nom"].astype(str).str.strip() != ""]
        after = len(rows)
        if before != after:
            log(f"   Lignes vides supprimées: {before} → {after}", log_file)

    log(f"   Colonnes finales: {list(df.columns)}", log_file)
    return df, rows


def convert_excel(excel_path: str, sheet_name: str, out_json: str, out_ndjson: str, out_csv: str, log_file: str, import_city: str = "Paris"):
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Fichier introuvable: {excel_path}")

    is_csv = excel_path.lower().endswith('.csv')

    if is_csv:
        # CSV : la première ligne est directement les en-têtes
        log("📄 Format CSV détecté", log_file)
        # Essayer plusieurs encodages courants
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                df = pd.read_csv(excel_path, encoding=encoding, sep=None, engine='python')
                log(f"📊 CSV chargé (encodage: {encoding}): {len(df)} lignes, {len(df.columns)} colonnes", log_file)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Impossible de lire le CSV — encodage non supporté")

        if len(df) == 0:
            raise ValueError("Le fichier CSV ne contient aucune donnée")

        rows = df.copy()
    else:
        xls = pd.ExcelFile(excel_path)
        log(f"📋 Feuilles disponibles: {xls.sheet_names}", log_file)

        if not xls.sheet_names:
            raise ValueError("Aucune feuille trouvée dans le fichier Excel")

        if sheet_name not in xls.sheet_names:
            sheet_name = xls.sheet_names[0]
            log(f"⚠️  Feuille '{sheet_name}' non trouvée, utilisation de: {sheet_name}", log_file)

        df = xls.parse(sheet_name)
        log(f"📊 Données chargées: {len(df)} lignes, {len(df.columns)} colonnes", log_file)

        if len(df) == 0:
            raise ValueError("Le fichier Excel ne contient aucune donnée")

        # Détection du format header selon la ville
        is_single_header = (import_city.lower() != "paris")

        if is_single_header:
            # Single header : row 0 = vrais headers (Marrakech, etc.)
            rows = df.copy()
            log(f"📋 Format single-header détecté (ville: {import_city})", log_file)
        else:
            # Double header : row 0 = catégories, row 1 = vrais headers (Paris)
            df.columns = df.iloc[0]
            rows = df.iloc[1:].copy()
            log(f"📋 Format double-header détecté (ville: {import_city})", log_file)

    # Normalisation des colonnes pour les villes non-Paris
    if import_city.lower() != "paris":
        df, rows = _normalize_marrakech_columns(df, rows, sheet_name, import_city, log_file)

    log(f"📝 Données à traiter: {len(rows)} lignes", log_file)
    
    # Variables pour le géocodage (utiliser des listes pour permettre la modification dans la fonction interne)
    geocoding_counter = [0]
    geocoding_stats = {"with_coords": 0, "needs_geocoding": 0, "no_address": 0}
    
    def row_to_flat_doc(row):
        entry = {}
        for col in df.columns:
            try:
                val = row[col]
                if isinstance(val, pd.Series):
                    non_null_values = val.dropna()
                    if len(non_null_values) > 0:
                        entry[col] = str(non_null_values.iloc[0])
                    else:
                        entry[col] = ""
                else:
                    if pd.notna(val):
                        entry[col] = str(val)
                    else:
                        entry[col] = ""
            except Exception as e:
                entry[col] = ""

        for group, tags in TAG_GROUPS.items():
            try:
                if group == "type_tags":
                    entry[group] = collect_type_tags_from_columns(row)
                elif group == "location_name":
                    entry[group] = collect_location_name_from_columns(row)
                else:
                    collected_tags = collect_tags_from_excel_columns(row, group)
                    entry[group] = ", ".join(collected_tags)
            except Exception as e:
                entry[group] = ""

        name = clean_text(entry.get("Vrai Nom") or entry.get("Nom de base") or "")
        raw_name = clean_text(entry.get("Nom de base") or "")
        tag = clean_text(entry.get("Ref") or entry.get("tag") or "")
        raw_address = clean_text(entry.get("Adresse") or "")
        all_addresses = parse_multi_addresses(raw_address)
        address = all_addresses[0]  # Premier élément = rétrocompat

        all_arrondissements = parse_arrondissements(entry.get("Arrondissement"))
        arrondissement = all_arrondissements[0]  # Premier élément = rétrocompat

        # --- Champs multi-ville / multi-type ---
        doc_city = clean_text(entry.get("Ville") or "")
        if not doc_city:
            doc_city = import_city  # fallback sur la ville du contexte d'import
        venue_type = clean_text(entry.get("Type de lieu") or "").lower()
        if venue_type not in ("restaurant", "hotel", "daypass"):
            venue_type = "restaurant"
        hotel_category = clean_text(entry.get("Catégorie hôtel") or entry.get("Categorie hotel") or "")
        price_per_night_raw = clean_text(entry.get("Prix par nuit") or "")
        price_per_night = None
        if price_per_night_raw:
            try:
                price_per_night = int(float(price_per_night_raw))
            except (ValueError, TypeError):
                pass
        equipements = to_list(entry.get("Équipements") or entry.get("Equipements") or "")
        star_rating = clean_text(entry.get("Étoiles") or entry.get("Etoiles") or entry.get("star_rating") or "")

        phone = clean_text(entry.get("Téléphone") or "")
        website = clean_text(entry.get("Site web") or "")
        reservation_link = clean_text(entry.get("Lien de réservation") or "")
        instagram_link = clean_text(entry.get("Lien de votre compte instagram") or "")
        instagram_video_link = clean_text(entry.get("Lien vidéo insta") or entry.get("Lien video insta") or entry.get("Lien vidéo instagram") or entry.get("Lien video instagram") or "")
        google_link = clean_text(entry.get("Lien Google") or "")
        lien_menu = clean_text(entry.get("Lien Menu") or "")
        hours_raw = clean_text(entry.get("Horaires") or "")
        hours_structured = process_hours(hours_raw) if hours_raw else {}
        commentaire = clean_text(entry.get("Infos") or "")

        lat_str = clean_text(entry.get("Latitude") or entry.get("latitude") or "")
        lon_str = clean_text(entry.get("Longitude") or entry.get("longitude") or "")

        # Log initial pour le restaurant
        restaurant_name = name or tag or "Restaurant inconnu"

        # Parse multi-coordonnées (séparées par ;)
        all_coords = parse_multi_coords(lat_str, lon_str)

        # Premier jeu de coordonnées = rétrocompat
        latitude = all_coords[0][0] if all_coords else None
        longitude = all_coords[0][1] if all_coords else None

        if latitude is not None and longitude is not None:
            if log_file:
                log(f"📍 [{restaurant_name}] Coordonnées trouvées dans Excel: lat={latitude:.6f}, lon={longitude:.6f}", log_file)

        # Vérifier si on a besoin de géocoder (uniquement l'adresse principale)
        needs_geocoding = (latitude is None or longitude is None) and address

        if needs_geocoding:
            geocoding_counter[0] += 1
            if log_file:
                missing = []
                if latitude is None:
                    missing.append("latitude")
                if longitude is None:
                    missing.append("longitude")
                log(f"🌍 [{restaurant_name}] [{geocoding_counter[0]}/{geocoding_stats['needs_geocoding']}] Démarrage géocodage - Adresse: '{address}' - Manque: {', '.join(missing)}", log_file)

            coords = geocode_address(address, log_file, restaurant_name=restaurant_name, city=doc_city)
            if coords:
                if latitude is None:
                    latitude = coords[0]
                    if log_file:
                        log(f"✅ [{restaurant_name}] Latitude obtenue par géocodage: {latitude:.6f}", log_file)
                if longitude is None:
                    longitude = coords[1]
                    if log_file:
                        log(f"✅ [{restaurant_name}] Longitude obtenue par géocodage: {longitude:.6f}", log_file)
                if log_file:
                    log(f"✅ [{restaurant_name}] [{geocoding_counter[0]}/{geocoding_stats['needs_geocoding']}] Géocodage terminé avec succès", log_file)
                # Mettre à jour les coords du premier élément
                if all_coords:
                    all_coords[0] = (latitude, longitude)
                else:
                    all_coords = [(latitude, longitude)]
                time.sleep(1.1)
            else:
                if log_file:
                    log(f"❌ [{restaurant_name}] [{geocoding_counter[0]}/{geocoding_stats['needs_geocoding']}] Géocodage échoué - Aucune coordonnée obtenue pour: '{address}'", log_file)
        elif not address:
            if log_file:
                log(f"⚠️  [{restaurant_name}] Pas d'adresse disponible pour géocodage", log_file)
        else:
            if log_file:
                log(f"✅ [{restaurant_name}] Coordonnées complètes (pas de géocodage nécessaire): lat={latitude:.6f}, lon={longitude:.6f}", log_file)

        if len(all_addresses) > 1 and log_file:
            log(f"📍 [{restaurant_name}] Multi-adresses détectées: {len(all_addresses)} adresses, arrondissements={all_arrondissements}", log_file)
        
        ambiance_tags = collect_tags_from_excel_columns(row, "ambiance")
        price_range = collect_tags_from_excel_columns(row, "price_range")
        preferences_tags = collect_tags_from_excel_columns(row, "preferences")
        lieu_tags = collect_tags_from_excel_columns(row, "lieu_tags")
        cuisines_tags = collect_tags_from_excel_columns(row, "cuisine")
        specialite_tag = string_to_tag_list(entry.get("Spécialité_TAG") or "")
        types_tags = collect_tags_from_excel_columns(row, "type_tags")
        moments_tags = collect_tags_from_excel_columns(row, "moment")
        terrace_tags = collect_tags_from_excel_columns(row, "terrace")
        recommended_by_tags = collect_tags_from_excel_columns(row, "recommended_by")
        
        affichage_fusionne = collect_affichage_tags(row)
        specialite_affichage = collect_specialite_affichage(row)
        
        cuisine_tag = cuisines_tags
        moment_tag = moments_tags
        lieu_tag = lieu_tags
        ambiance_tag = ambiance_tags
        preferences_tag = preferences_tags
        type_tag = types_tags
        recommended_by_tag = recommended_by_tags
        
        has_terrace = any("terrasse" in x.lower() for x in (ambiance_tags + lieu_tags + terrace_tags))
        terrace_locs = [x for x in (lieu_tags + terrace_tags) if "terrasse" in x.lower()]
        
        # Parse des stations de métro — support multi-adresses (séparées par |)
        raw_station1 = entry.get("Station de metro 1", "").strip()
        raw_lignes1 = entry.get("Lignes 1", "").strip()
        raw_station2 = entry.get("Stations de metro 2 ", "").strip()
        raw_lignes2 = entry.get("Lignes 2 ", "").strip()

        num_addresses = len(all_addresses)
        is_multi = num_addresses > 1

        if is_multi:
            # Multi-adresses : splitter par | pour distribuer les stations par adresse
            stations1_parts = [s.strip() for s in raw_station1.split("|")] if raw_station1 else []
            lignes1_parts = [s.strip() for s in raw_lignes1.split("|")] if raw_lignes1 else []
            stations2_parts = [s.strip() for s in raw_station2.split("|")] if raw_station2 else []
            lignes2_parts = [s.strip() for s in raw_lignes2.split("|")] if raw_lignes2 else []

            # Construire les stations par adresse
            per_address_metros = []
            for i in range(num_addresses):
                addr_metros = []
                # Station 1 pour cette adresse
                s1 = stations1_parts[i].strip() if i < len(stations1_parts) else ""
                l1 = lignes1_parts[i].strip() if i < len(lignes1_parts) else ""
                if s1 and s1.lower() not in ["non", "", "nan"]:
                    lines1 = [l.strip() for l in l1.split(",") if l.strip()] if l1 else []
                    addr_metros.append({"station": s1, "lines": lines1})
                # Station 2 pour cette adresse
                s2 = stations2_parts[i].strip() if i < len(stations2_parts) else ""
                l2 = lignes2_parts[i].strip() if i < len(lignes2_parts) else ""
                if s2 and s2.lower() not in ["non", "", "nan"]:
                    lines2 = [l.strip() for l in l2.split(",") if l.strip()] if l2 else []
                    addr_metros.append({"station": s2, "lines": lines2})
                per_address_metros.append(addr_metros)

            # Root stations_metro = celles de la première adresse
            stations_metro = per_address_metros[0] if per_address_metros else []
        else:
            # Adresse unique : comportement classique
            stations_metro = []
            if raw_station1 and raw_station1.lower() not in ["non", "", "nan"]:
                lines1 = [l.strip() for l in raw_lignes1.split(",") if l.strip()] if raw_lignes1 else []
                stations_metro.append({"station": raw_station1, "lines": lines1})
            if raw_station2 and raw_station2.lower() not in ["non", "", "nan"]:
                lines2 = [l.strip() for l in raw_lignes2.split(",") if l.strip()] if raw_lignes2 else []
                stations_metro.append({"station": raw_station2, "lines": lines2})
            per_address_metros = [stations_metro]

        # Construire le tableau multi-adresses pour Firestore
        addresses_array = []
        for i in range(num_addresses):
            addr_entry = {
                "address": all_addresses[i],
                "arrondissement": all_arrondissements[i] if i < len(all_arrondissements) else "",
                "latitude": all_coords[i][0] if i < len(all_coords) else None,
                "longitude": all_coords[i][1] if i < len(all_coords) else None,
                "stations_metro": per_address_metros[i] if i < len(per_address_metros) else [],
            }
            addresses_array.append(addr_entry)

        rid = normalize_id_from_tag(tag)
        # Tag normalisé en MAJUSCULES pour cohérence avec l'ID Firestore et les chemins
        # de logos/photos (Logos/{tag}1.webp). Insensible à la casse côté Excel.
        tag_normalized = rid
        doc = {
            "id": rid,
            "tag": tag_normalized,
            "name": name,
            "raw_name": raw_name,
            "address": address,
            "arrondissement": arrondissement,
            "latitude": latitude,
            "longitude": longitude,
            "phone": phone,
            "website": website,
            "reservation_link": reservation_link,
            "instagram_link": instagram_link,
            "instagram_video_link": instagram_video_link,
            "google_link": google_link,
            "lien_menu": lien_menu,
            "more_info": commentaire,
            "hours": hours_raw,
            "hours_structured": hours_structured,
            "affichage": affichage_fusionne,
            "specialite_affichage": specialite_affichage,
            "cuisine_tag": cuisine_tag,
            "specialite_tag": specialite_tag,
            "moment_tag": moment_tag,
            "lieu_tag": lieu_tag,
            "ambiance_tag": ambiance_tag,
            "preferences_tag": preferences_tag,
            "type_tag": type_tag,
            "recommended_by_tag": recommended_by_tag,
            "types": types_tags,
            "moments": moments_tags,
            "lieux": lieu_tags,
            "ambiance": ambiance_tags,
            "price_range": price_range,
            "cuisines": cuisines_tags,
            "preferences": preferences_tags,
            "recommended_by": recommended_by_tags,
            "tag_initial": [tag_normalized] if tag_normalized else [],
            "restaurant_type": types_tags,
            "location_type": lieu_tags,
            "extras": terrace_tags,
            "has_terrace": bool(has_terrace),
            "terrace_locs": terrace_locs,
            "stations_metro": stations_metro,
            "specialite_tag": specialite_tag,
            "lieu_tag": lieu_tag,
            # Multi-adresses
            "addresses": addresses_array,
            "arrondissements": all_arrondissements,
            # Multi-ville / multi-type
            "city": doc_city,
            "venue_type": venue_type,
        }
        # Champs hôtel / daypass (ajoutés uniquement si pertinents)
        if hotel_category:
            doc["hotel_category"] = hotel_category
        if price_per_night is not None:
            doc["price_per_night"] = price_per_night
        if equipements:
            doc["equipements"] = equipements
        if star_rating:
            doc["star_rating"] = star_rating
        return rid, doc

    # Première passe : compter les restaurants nécessitant un géocodage
    log("🔍 Analyse préliminaire : comptage des restaurants nécessitant un géocodage...", log_file)
    geocoding_stats = {"with_coords": 0, "needs_geocoding": 0, "no_address": 0}
    
    for idx, row in rows.iterrows():
        entry = {}
        for col in df.columns:
            try:
                val = row[col]
                if isinstance(val, pd.Series):
                    non_null_values = val.dropna()
                    if len(non_null_values) > 0:
                        entry[col] = str(non_null_values.iloc[0])
                    else:
                        entry[col] = ""
                else:
                    if pd.notna(val):
                        entry[col] = str(val)
                    else:
                        entry[col] = ""
            except Exception:
                entry[col] = ""
        
        raw_addr = clean_text(entry.get("Adresse") or "")
        first_address = parse_multi_addresses(raw_addr)[0]
        lat_str = clean_text(entry.get("Latitude") or entry.get("latitude") or "")
        lon_str = clean_text(entry.get("Longitude") or entry.get("longitude") or "")

        # Vérifier si les premières coordonnées sont parsables
        first_coords = parse_multi_coords(lat_str, lon_str)
        has_lat = first_coords and first_coords[0][0] is not None
        has_lon = first_coords and first_coords[0][1] is not None

        if has_lat and has_lon:
            geocoding_stats["with_coords"] += 1
        elif first_address:
            geocoding_stats["needs_geocoding"] += 1
        else:
            geocoding_stats["no_address"] += 1
    
    log(f"📊 Statistiques géocodage: {geocoding_stats['with_coords']} avec coordonnées, {geocoding_stats['needs_geocoding']} nécessitent géocodage, {geocoding_stats['no_address']} sans adresse", log_file)
    log(f"🌍 Démarrage du traitement avec géocodage pour {geocoding_stats['needs_geocoding']} restaurants...", log_file)
    
    records = []
    ids = []
    missing_tag_rows = []
    total_rows = len(rows)
    log(f"🔄 Conversion de {total_rows} lignes Excel en documents Firebase...", log_file)
    for count, (idx, row) in enumerate(rows.iterrows(), 1):
        if count % 10 == 0 or count == 1:
            log(f"   📊 Progression: {count}/{total_rows} restaurants traités", log_file)
        rid, doc = row_to_flat_doc(row)
        if not rid:
            missing_tag_rows.append(idx + 2)
            continue
        ids.append(rid)
        records.append(doc)

    dup_counts = Counter([i for i in ids if i])
    duplicates = [k for k, c in dup_counts.items() if c > 1]

    if duplicates:
        log(f"⚠️  IDs dupliqués détectés: {duplicates}", log_file)
    if missing_tag_rows:
        log(f"⚠️  Lignes sans tag (Ref) : {missing_tag_rows}", log_file)

    if DEDUPE_IDS and duplicates:
        seen = {}
        for r in records:
            rid = r["id"]
            if not rid:
                continue
            if rid not in seen:
                seen[rid] = 1
            else:
                seen[rid] += 1
                r["id"] = f"{rid}-{seen[rid]}"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    with open(out_ndjson, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    csv_rows = []
    for doc in records:
        csv_rows.append({
            "id": doc.get("id", ""),
            "tag": doc.get("tag", ""),
            "name": doc.get("name", ""),
            "raw_name": doc.get("raw_name", ""),
            "address": doc.get("address", ""),
            "arrondissement": doc.get("arrondissement", ""),
            "latitude": doc.get("latitude") if doc.get("latitude") is not None else "",
            "longitude": doc.get("longitude") if doc.get("longitude") is not None else "",
            "phone": doc.get("phone", ""),
            "website": doc.get("website", ""),
            "google_link": doc.get("google_link", ""),
            "reservation_link": doc.get("reservation_link", ""),
            "instagram_link": doc.get("instagram_link", ""),
            "instagram_video_link": doc.get("instagram_video_link", ""),
            "lien_menu": doc.get("lien_menu", ""),
            "more_info": doc.get("more_info", ""),
            "hours": doc.get("hours", ""),
            "affichage": ", ".join(doc.get("affichage", [])),
            "specialite_affichage": doc.get("specialite_affichage", ""),
            "types": ", ".join(doc.get("types", [])),
            "moments": ", ".join(doc.get("moments", [])),
            "lieux": ", ".join(doc.get("lieux", [])),
            "ambiance": ", ".join(doc.get("ambiance", [])),
            "price_range": doc.get("price_range", ""),
            "cuisines": ", ".join(doc.get("cuisines", [])),
            "preferences": ", ".join(doc.get("preferences", [])),
            "recommended_by": ", ".join(doc.get("recommended_by", [])),
            "tag_initial": ", ".join(doc.get("tag_initial", [])),
            "restaurant_type": ", ".join(doc.get("restaurant_type", [])),
            "location_type": ", ".join(doc.get("location_type", [])),
            "extras": ", ".join(doc.get("extras", [])),
            "has_terrace": doc.get("has_terrace", False),
            "terrace_locs": ", ".join(doc.get("terrace_locs", [])),
            "specialite_tag": doc.get("specialite_tag", ""),
            "lieu_tag": doc.get("lieu_tag", "")
        })
    
    with open(out_csv, "w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=list(csv_rows[0].keys()) if csv_rows else 
                                ["id","tag","name","raw_name","address","arrondissement","latitude","longitude","phone","website","google_link","reservation_link","instagram_link","instagram_video_link","lien_menu","more_info","hours","types","moments","lieux","ambiance","price_range","cuisines","preferences","recommended_by","has_terrace","terrace_locs","specialite_tag","lieu_tag"])
        writer.writeheader()
        for r in csv_rows:
            writer.writerow(r)
    
    log(f"📄 CSV temporaire créé: {out_csv}", log_file)
    return records, {"duplicates": duplicates, "missing_tag_rows": missing_tag_rows}

# -------------------- Clean & Import --------------------
def delete_collection(db, collection_name: str, batch_size: int, log_file: str, city: str = None, venue_type: str = None) -> int:
    """Supprime les documents d'une collection. Si city est fourni, supprime uniquement les docs de cette ville.
    Si venue_type est fourni, supprime uniquement les docs de ce type (restaurant, hotel, daypass)."""
    total_deleted = 0
    while True:
        query = db.collection(collection_name)
        if city:
            query = query.where("city", "==", city)
        if venue_type:
            query = query.where("venue_type", "==", venue_type)
        docs = list(query.limit(batch_size).stream())
        if not docs:
            break
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
        total_deleted += len(docs)
        scope_parts = []
        if city:
            scope_parts.append(city)
        if venue_type:
            scope_parts.append(venue_type)
        scope = f" ({', '.join(scope_parts)})" if scope_parts else ""
        log(f"🗑️  Supprimés cumulés{scope}: {total_deleted}", log_file)
    return total_deleted

def import_records(db, collection_name: str, records: List[Dict[str, Any]], batch_size: int, log_file: str) -> int:
    imported = 0
    skipped = 0
    collection = db.collection(collection_name)
    
    for doc in records:
        rid = (doc.get("id") or "").strip()
        if not rid or not isinstance(doc, dict):
            skipped += 1
            log(f"⏭️  skip: id/doc invalides → {doc}", log_file)
            continue
        try:
            doc_ref = collection.document(rid)
            doc_ref.set(doc, merge=True)
            imported += 1
            if imported % 50 == 0:
                log(f"📥 Importés: {imported}", log_file)
        except Exception as e:
            log(f"❌ Erreur doc {rid}: {e}", log_file)
            skipped += 1
            continue
    
    log(f"📥 Importés: {imported}", log_file)
    return imported

def write_import_log(db, collection_logs: str, payload: Dict[str, Any], log_file: str):
    data = dict(payload)
    data["server_timestamp"] = firestore.SERVER_TIMESTAMP
    db.collection(collection_logs).add(data)
    log("📝 Log d'import écrit dans Firestore.", log_file)

# -------------------- Favorite Count Update --------------------
def update_favorite_counts(db, log_file: str) -> Dict[str, Any]:
    """
    Met à jour le champ favorite_count dans chaque document restaurant
    en comptant les favoris actifs depuis la collection favorites.
    
    Returns:
        Dictionnaire avec les statistiques de mise à jour
    """
    from collections import defaultdict
    
    stats = {
        "total_favorites": 0,
        "active_favorites": 0,
        "restaurants_with_favorites": 0,
        "updated": 0,
        "errors": 0,
        "zero_initialized": 0
    }
    
    try:
        # 1) Compter les favoris actifs par restaurantId
        log("📊 Récupération des favoris actifs...", log_file)
        favorites_ref = db.collection('favorites')
        restaurant_counts = defaultdict(int)
        
        docs = favorites_ref.stream()
        for doc in docs:
            stats["total_favorites"] += 1
            data = doc.to_dict()
            
            # Vérifier si le favori est actif
            status = data.get('status', 'active')
            if status != 'inactive':
                stats["active_favorites"] += 1
                restaurant_id = data.get('restaurantId')
                if restaurant_id:
                    restaurant_counts[restaurant_id] += 1
        
        stats["restaurants_with_favorites"] = len(restaurant_counts)
        log(f"✅ {stats['total_favorites']} favoris trouvés, {stats['active_favorites']} actifs, {stats['restaurants_with_favorites']} restaurants concernés", log_file)
        
        # 2) Mettre à jour les compteurs dans les restaurants
        log("🔄 Mise à jour des compteurs dans les restaurants...", log_file)
        restaurants_ref = db.collection('restaurants')
        
        for restaurant_id, count in restaurant_counts.items():
            try:
                restaurant_ref = restaurants_ref.document(restaurant_id)
                restaurant_doc = restaurant_ref.get()
                
                if restaurant_doc.exists:
                    restaurant_ref.update({
                        'favorite_count': count
                    })
                    stats["updated"] += 1
                    if stats["updated"] % 50 == 0:
                        log(f"   ✓ {stats['updated']} restaurants mis à jour...", log_file)
                else:
                    log(f"   ⚠️  Restaurant {restaurant_id} n'existe pas, ignoré", log_file)
                    stats["errors"] += 1
            except Exception as e:
                log(f"   ❌ Erreur pour le restaurant {restaurant_id}: {e}", log_file)
                stats["errors"] += 1
        
        log(f"✅ {stats['updated']} restaurants mis à jour avec succès", log_file)
        
        # 3) Initialiser à 0 les restaurants sans favoris
        log("🔄 Initialisation des restaurants sans favoris à 0...", log_file)
        restaurants_with_favorites = set(restaurant_counts.keys())
        
        all_restaurants = restaurants_ref.stream()
        for restaurant_doc in all_restaurants:
            restaurant_id = restaurant_doc.id
            data = restaurant_doc.to_dict()
            
            # Si le restaurant n'a pas de favorite_count défini et n'a pas de favoris
            if 'favorite_count' not in data and restaurant_id not in restaurants_with_favorites:
                try:
                    restaurant_doc.reference.update({
                        'favorite_count': 0
                    })
                    stats["zero_initialized"] += 1
                    if stats["zero_initialized"] % 50 == 0:
                        log(f"   ✓ {stats['zero_initialized']} restaurants initialisés à 0...", log_file)
                except Exception as e:
                    log(f"   ❌ Erreur pour le restaurant {restaurant_id}: {e}", log_file)
                    stats["errors"] += 1
        
        log(f"✅ {stats['zero_initialized']} restaurants initialisés à 0", log_file)
        
    except Exception as e:
        log(f"❌ Erreur lors de la mise à jour des compteurs de favoris: {e}\n{traceback.format_exc()}", log_file)
        stats["errors"] += 1
        raise
    
    return stats

# -------------------- Main --------------------
def import_restaurants_from_excel(excel_path: str, sheet_name: str = "Feuil1", request=None, log_file_path=None, city: str = None):
    """
    Fonction principale d'import adaptée pour Django.
    Fonctionne en DEV et en PROD - seule la base de données Firebase change selon l'environnement.

    Import par ville : si city est fourni, seuls les documents de cette ville sont backupés,
    supprimés et remplacés. Les restaurants des autres villes restent intacts.

    Args:
        excel_path: Chemin vers le fichier Excel
        sheet_name: Nom de la feuille Excel (défaut: "Feuil1")
        request: Objet request Django (optionnel) pour déterminer l'environnement Firebase
        log_file_path: Chemin du fichier de log (optionnel, sinon créé automatiquement)
        city: Ville cible de l'import (ex: "Paris", "Marrakech"). Si None, import global (legacy).
    """
    # Détecter l'environnement Firebase (dev ou prod)
    try:
        from scripts_manager.firebase_utils import get_firebase_env_from_session
        current_env = get_firebase_env_from_session(request)
    except ImportError:
        # Fallback si firebase_utils n'est pas disponible
        current_env = os.getenv('FIREBASE_ENV', 'prod').lower()

    if log_file_path:
        log_file = log_file_path
        backup_dir = os.path.dirname(log_file)
    else:
        ts_dir = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        city_suffix = f"_{city.lower()}" if city else ""
        backup_dir = os.path.join(BACKUP_DIR, f"{COLLECTION_SOURCE}{city_suffix}_{ts_dir}")
        ensure_dir(backup_dir)
        log_file = os.path.join(backup_dir, "import_run.log")

    import_city = city or "Paris"

    file_type = "CSV" if excel_path.lower().endswith('.csv') else "Excel"
    log("🚀 Démarrage import end-to-end", log_file)
    log(f"→ Fichier ({file_type}): {excel_path}", log_file)
    log(f"→ Environnement: {current_env.upper()}", log_file)
    log(f"→ Ville: {import_city}" + (" (import global)" if not city else " (import par ville)"), log_file)

    try:
        db = init_firestore(log_file, request)
    except Exception as e:
        log(f"❌ Init Firestore échouée: {e}\n{traceback.format_exc()}", log_file)
        raise

    # 1) Backup — uniquement les documents de la ville cible si city-scoped
    backup_meta = {}
    try:
        scope_label = f"'{COLLECTION_SOURCE}' (ville: {import_city})" if city else f"'{COLLECTION_SOURCE}'"
        log(f"🗄️  Backup de {scope_label} ...", log_file)
        backup_meta = export_collection(db, COLLECTION_SOURCE, backup_dir, log_file, city=city)
    except Exception as e:
        log(f"❌ Backup échoué: {e}\n{traceback.format_exc()}", log_file)
        raise

    # 2) Convert Excel → records
    try:
        out_json = os.path.join(backup_dir, "restaurants_from_excel_by_tag.json")
        out_ndjson = os.path.join(backup_dir, "restaurants_from_excel_by_tag.ndjson")
        out_csv = os.path.join(backup_dir, "restaurants_from_excel_by_tag.csv")
        log(f"🔁 Conversion {file_type} → JSON/NDJSON/CSV ...", log_file)
        records, conv_report = convert_excel(excel_path, sheet_name, out_json, out_ndjson, out_csv, log_file, import_city=import_city)
        if not records:
            log("❌ Conversion a produit 0 enregistrements. Abandon.", log_file)
            raise ValueError("Conversion a produit 0 enregistrements")
        # Vérifier cohérence des villes dans l'Excel
        cities_in_records = set(r.get("city", "") for r in records)
        if city and len(cities_in_records) > 1:
            log(f"⚠️  Attention : l'Excel contient des restaurants de plusieurs villes : {cities_in_records}", log_file)
        log(f"✅ Conversion OK ({len(records)} docs). Duplicates: {len(conv_report['duplicates'])}, Missing tags rows: {len(conv_report['missing_tag_rows'])}", log_file)
    except Exception as e:
        log(f"❌ Conversion échouée: {e}\n{traceback.format_exc()}", log_file)
        raise

    # 3) Clean collection — scopé par ville ET venue_type pour ne pas écraser les autres types
    import_venue_type = SHEET_VENUE_TYPE.get(sheet_name)
    try:
        scope_parts = []
        if city:
            scope_parts.append(f"ville: {import_city}")
        if import_venue_type:
            scope_parts.append(f"type: {import_venue_type}")
        scope_label = f"'{COLLECTION_SOURCE}' ({', '.join(scope_parts)})" if scope_parts else f"'{COLLECTION_SOURCE}'"
        log(f"🧹 Suppression de {scope_label} ...", log_file)
        deleted = delete_collection(db, COLLECTION_SOURCE, BATCH_SIZE, log_file, city=city, venue_type=import_venue_type)
        log(f"✅ Suppression terminée: {deleted} documents supprimés.", log_file)
    except Exception as e:
        log(f"❌ Suppression échouée: {e}\n{traceback.format_exc()}", log_file)
        raise

    # 4) Import
    try:
        log(f"🚚 Import de {len(records)} documents ...", log_file)
        imported = import_records(db, COLLECTION_SOURCE, records, BATCH_SIZE, log_file)
        log(f"✅ Import terminé: {imported} documents importés.", log_file)
    except Exception as e:
        log(f"❌ Import échoué: {e}\n{traceback.format_exc()}", log_file)
        raise

    # 5) Import log document
    try:
        payload = {
            "collection": COLLECTION_SOURCE,
            "imported_count": imported,
            "city": import_city,
            "city_scoped": bool(city),
            "source": os.path.basename(out_csv),
            "timestamp": now_paris_str(),
            "backup_dir": backup_dir,
            "backup_count": backup_meta.get("count", 0),
            "backup_json_sha256": backup_meta.get("sha256_json"),
            "backup_ndjson_sha256": backup_meta.get("sha256_ndjson"),
            "duplicates_count": len(conv_report.get("duplicates", [])),
            "missing_tag_rows": conv_report.get("missing_tag_rows", []),
        }
        write_import_log(db, COLLECTION_IMPORT_LOGS, payload, log_file)
    except Exception as e:
        log(f"❌ Écriture du log d'import échouée: {e}\n{traceback.format_exc()}", log_file)

    # 6) Mise à jour des compteurs de favoris
    favorite_count_stats = {}
    try:
        log("❤️  Mise à jour des compteurs de favoris...", log_file)
        favorite_count_stats = update_favorite_counts(db, log_file)
        log(f"✅ Compteurs de favoris mis à jour: {favorite_count_stats.get('updated', 0)} restaurants", log_file)
    except Exception as e:
        log(f"⚠️  Erreur lors de la mise à jour des compteurs de favoris: {e}\n{traceback.format_exc()}", log_file)
        # Ne pas faire échouer l'import si le comptage des favoris échoue
        favorite_count_stats = {"error": str(e)}

    log("🎉 Fin de workflow end-to-end.", log_file)
    return {
        "success": True,
        "imported": imported,
        "backup_dir": backup_dir,
        "log_file": log_file,
        "duplicates": len(conv_report.get("duplicates", [])),
        "missing_tag_rows": len(conv_report.get("missing_tag_rows", [])),
        "favorite_count_stats": favorite_count_stats
    }

