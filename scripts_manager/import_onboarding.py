"""
Import des restaurants d'onboarding depuis un fichier Excel vers Firestore.
Collection cible : onboarding_restaurants (indépendante de 'restaurants')
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

from .firebase_utils import get_service_account_path, get_firebase_env_from_session

logger = logging.getLogger(__name__)

ONBOARDING_COLLECTION = 'onboarding_restaurants'

# App Firebase dédiée à l'onboarding (gérée par environnement)
_FIREBASE_APP = None
_FIREBASE_APP_ENV = None

# Colonnes attendues dans l'Excel
EXPECTED_COLUMNS = {
    'nom': ['Nom du restaurant', 'Nom', 'nom du restaurant', 'nom'],
    'tag': ['Tag', 'tag', 'TAG'],
    'lieu': ['Lieu', 'lieu', 'LIEU'],
    'specialite': ['Spécialité', 'Specialité', 'specialite', 'Spécialite', 'SPECIALITE'],
}


def _get_firebase_app(request=None):
    """Initialise et retourne l'app Firebase Admin pour l'environnement actif."""
    global _FIREBASE_APP, _FIREBASE_APP_ENV

    current_env = get_firebase_env_from_session(request)

    # Si l'app existe mais pour un autre environnement, la réinitialiser
    if _FIREBASE_APP and _FIREBASE_APP_ENV != current_env:
        logger.info(f"Onboarding: changement d'env {_FIREBASE_APP_ENV} -> {current_env}")
        try:
            firebase_admin.delete_app(_FIREBASE_APP)
        except Exception:
            pass
        _FIREBASE_APP = None
        _FIREBASE_APP_ENV = None

    if _FIREBASE_APP:
        return _FIREBASE_APP

    service_account_path = get_service_account_path(request)
    logger.info(f"Onboarding: init Firebase env={current_env} (fichier: {service_account_path})")

    if not os.path.exists(service_account_path):
        logger.error(f"serviceAccountKey.json introuvable: {service_account_path}")
        return None

    try:
        cred = credentials.Certificate(service_account_path)
        _FIREBASE_APP = firebase_admin.initialize_app(cred, name='onboarding')
        _FIREBASE_APP_ENV = current_env
    except ValueError:
        # App 'onboarding' déjà initialisée — la supprimer et recréer avec le bon env
        try:
            old_app = firebase_admin.get_app('onboarding')
            firebase_admin.delete_app(old_app)
        except ValueError:
            pass
        cred = credentials.Certificate(service_account_path)
        _FIREBASE_APP = firebase_admin.initialize_app(cred, name='onboarding')
        _FIREBASE_APP_ENV = current_env

    return _FIREBASE_APP


def get_firestore_client(request=None):
    """Retourne un client Firestore configuré selon l'environnement actif."""
    app = _get_firebase_app(request)
    if not app:
        return None
    return firestore.client(app)


def find_column(df_columns, possible_names):
    """Trouve le nom réel d'une colonne parmi les variantes possibles."""
    for name in possible_names:
        if name in df_columns:
            return name
    return None


def clean_text(value):
    """Nettoie une valeur texte : strips, remplace espaces insécables, etc."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    # Remplacer les espaces insécables
    s = s.replace('\u00a0', ' ').replace('\u200b', '')
    if not s or s.lower() in ('nan', 'none', 'null', ''):
        return None
    return s


def parse_onboarding_excel(excel_path, sheet_name=None):
    """
    Parse le fichier Excel d'onboarding et retourne les enregistrements.

    Args:
        excel_path: Chemin vers le fichier Excel
        sheet_name: Nom de la feuille (optionnel, utilise la première par défaut)

    Returns:
        tuple: (records, report)
            - records: Liste de dicts prêts pour Firestore
            - report: Dict avec les statistiques du parsing
    """
    report = {
        'total_rows': 0,
        'valid_rows': 0,
        'skipped_rows': 0,
        'errors': [],
        'by_lieu': {},
        'by_specialite': {},
    }

    try:
        xls = pd.ExcelFile(excel_path)
        available_sheets = xls.sheet_names

        if sheet_name and sheet_name in available_sheets:
            df = pd.read_excel(xls, sheet_name=sheet_name)
        else:
            df = pd.read_excel(xls, sheet_name=0)
            sheet_name = available_sheets[0]

        report['sheet_name'] = sheet_name
        report['available_sheets'] = available_sheets
    except Exception as e:
        report['errors'].append(f"Erreur lecture Excel: {str(e)}")
        return [], report

    # Trouver les colonnes
    col_nom = find_column(df.columns, EXPECTED_COLUMNS['nom'])
    col_tag = find_column(df.columns, EXPECTED_COLUMNS['tag'])
    col_lieu = find_column(df.columns, EXPECTED_COLUMNS['lieu'])
    col_specialite = find_column(df.columns, EXPECTED_COLUMNS['specialite'])

    missing_cols = []
    if not col_nom:
        missing_cols.append('Nom du restaurant')
    if not col_tag:
        missing_cols.append('Tag')
    if not col_lieu:
        missing_cols.append('Lieu')

    if missing_cols:
        report['errors'].append(f"Colonnes manquantes: {', '.join(missing_cols)}")
        return [], report

    report['columns_found'] = {
        'nom': col_nom,
        'tag': col_tag,
        'lieu': col_lieu,
        'specialite': col_specialite,
    }

    records = []
    seen_tags = set()

    for idx, row in df.iterrows():
        report['total_rows'] += 1

        nom = clean_text(row.get(col_nom))
        tag = clean_text(row.get(col_tag))
        lieu = clean_text(row.get(col_lieu))
        specialite = clean_text(row.get(col_specialite)) if col_specialite else None

        # Skip lignes vides
        if not nom and not tag:
            report['skipped_rows'] += 1
            continue

        # Tag obligatoire
        if not tag:
            report['errors'].append(f"Ligne {idx + 2}: Tag manquant pour '{nom}'")
            report['skipped_rows'] += 1
            continue

        tag_upper = tag.upper().strip()

        # Vérifier les doublons
        if tag_upper in seen_tags:
            report['errors'].append(f"Ligne {idx + 2}: Tag dupliqué '{tag_upper}'")
            report['skipped_rows'] += 1
            continue
        seen_tags.add(tag_upper)

        # Valider le lieu
        valid_lieux = ['Restaurant', 'Coffee shop', 'Bar']
        if lieu and lieu not in valid_lieux:
            # Tenter une normalisation
            lieu_lower = lieu.lower().strip()
            if lieu_lower in ('coffee shop', 'coffeeshop', 'coffee', 'café'):
                lieu = 'Coffee shop'
            elif lieu_lower in ('bar', 'bars'):
                lieu = 'Bar'
            elif lieu_lower in ('restaurant', 'resto'):
                lieu = 'Restaurant'
            else:
                report['errors'].append(f"Ligne {idx + 2}: Lieu inconnu '{lieu}' pour '{nom}'")

        record = {
            'id': tag_upper,
            'name': nom or tag_upper,
            'tag': tag_upper,
            'lieu': lieu or 'Restaurant',
            'specialite': specialite,
            'logo_url': None,
            'image_urls': [],
        }

        records.append(record)
        report['valid_rows'] += 1

        # Stats
        lieu_key = record['lieu']
        report['by_lieu'][lieu_key] = report['by_lieu'].get(lieu_key, 0) + 1
        if specialite:
            report['by_specialite'][specialite] = report['by_specialite'].get(specialite, 0) + 1

    return records, report


def import_to_firestore(records, request=None, clear_first=True):
    """
    Importe les enregistrements dans la collection onboarding_restaurants.

    Args:
        records: Liste de dicts à importer
        request: Django request pour l'environnement
        clear_first: Si True, vide la collection avant import

    Returns:
        dict: Résultat de l'import
    """
    result = {
        'success': False,
        'imported': 0,
        'deleted': 0,
        'errors': [],
        'env': get_firebase_env_from_session(request),
    }

    try:
        db = get_firestore_client(request)
        collection_ref = db.collection(ONBOARDING_COLLECTION)

        # Vider la collection si demandé
        if clear_first:
            existing_docs = collection_ref.stream()
            batch = db.batch()
            count = 0
            for doc in existing_docs:
                batch.delete(doc.reference)
                count += 1
                if count % 400 == 0:
                    batch.commit()
                    batch = db.batch()
            if count % 400 != 0:
                batch.commit()
            result['deleted'] = count

        # Importer les nouveaux enregistrements
        now = datetime.utcnow().isoformat()
        batch = db.batch()
        imported = 0

        for record in records:
            doc_ref = collection_ref.document(record['id'])
            doc_data = {
                **record,
                'created_at': now,
                'updated_at': now,
            }
            batch.set(doc_ref, doc_data)
            imported += 1

            if imported % 400 == 0:
                batch.commit()
                batch = db.batch()

        if imported % 400 != 0:
            batch.commit()

        result['imported'] = imported
        result['success'] = True

    except Exception as e:
        logger.error(f"Erreur import onboarding: {e}")
        result['errors'].append(str(e))

    return result


def get_all_onboarding_restaurants(request=None):
    """Récupère tous les restaurants d'onboarding depuis Firestore."""
    try:
        db = get_firestore_client(request)
        docs = db.collection(ONBOARDING_COLLECTION).stream()
        restaurants = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            restaurants.append(data)
        return restaurants
    except Exception as e:
        logger.error(f"Erreur lecture onboarding_restaurants: {e}")
        return []


def get_onboarding_restaurant(restaurant_id, request=None):
    """Récupère un seul restaurant d'onboarding."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(ONBOARDING_COLLECTION).document(restaurant_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    except Exception as e:
        logger.error(f"Erreur lecture onboarding restaurant {restaurant_id}: {e}")
        return None


def delete_onboarding_restaurant(restaurant_id, request=None):
    """Supprime un restaurant d'onboarding."""
    try:
        db = get_firestore_client(request)
        db.collection(ONBOARDING_COLLECTION).document(restaurant_id).delete()
        return True
    except Exception as e:
        logger.error(f"Erreur suppression onboarding restaurant {restaurant_id}: {e}")
        return False
