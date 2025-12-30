"""
Vues pour la gestion et l'exploration des utilisateurs Firebase
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import firebase_admin
import pandas as pd
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.utils import timezone as django_timezone
from django.contrib.auth.decorators import login_required
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, firestore

from config import SERVICE_ACCOUNT_PATH, EXPORTS_DIR
from .firebase_utils import get_service_account_path

logger = logging.getLogger(__name__)

FIREBASE_APP = None
FIREBASE_APP_ENV = None  # Stocker l'environnement utilisé pour l'app
ONLINE_THRESHOLD_MINUTES = 15
RECENT_THRESHOLD_DAYS = 7

USERS_CACHE_KEY = 'users_merged_cache_v1'
MERGE_USERS_CACHE_KEY = 'merged_users_cache_v1'
MERGE_USERS_CACHE_TTL = int(os.getenv('MERGE_USERS_CACHE_TTL', 600))  # 10 minutes
USERS_CACHE_TTL = int(os.getenv('USERS_CACHE_TTL', os.getenv('CACHE_TTL', 180)))
FIRESTORE_USERS_CACHE_KEY = 'firestore_users_cache_v1'
FIRESTORE_USERS_CACHE_TTL = int(os.getenv('FIRESTORE_USERS_CACHE_TTL', 180))
AUTH_USERS_CACHE_KEY = 'firebase_auth_users_cache_v1'
AUTH_USERS_CACHE_TTL = int(os.getenv('AUTH_USERS_CACHE_TTL', 180))
FCM_TOKENS_CACHE_KEY = 'fcm_tokens_cache_v1'
FCM_TOKENS_CACHE_TTL = int(os.getenv('FCM_TOKENS_CACHE_TTL', 180))
USERS_PAGE_SIZE = int(os.getenv('USERS_PAGE_SIZE', 50))


def get_firebase_app(request=None):
    """
    Initialise (si nécessaire) et retourne l'app Firebase Admin.
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement depuis la session
    """
    global FIREBASE_APP, FIREBASE_APP_ENV
    
    # Récupérer l'environnement actuel
    from .firebase_utils import get_firebase_env_from_session
    current_env = get_firebase_env_from_session(request)
    
    # Si l'app existe mais pour un autre environnement, la réinitialiser
    if FIREBASE_APP and FIREBASE_APP_ENV != current_env:
        logger.info(f"🔄 Changement d'environnement détecté: {FIREBASE_APP_ENV} -> {current_env}. Réinitialisation de l'app Firebase.")
        try:
            firebase_admin.delete_app(FIREBASE_APP)
        except Exception as e:
            logger.warning(f"Erreur lors de la suppression de l'app Firebase: {e}")
        FIREBASE_APP = None
        FIREBASE_APP_ENV = None
    
    if FIREBASE_APP:
        return FIREBASE_APP

    # Récupérer le chemin selon l'environnement
    service_account_path = get_service_account_path(request)
    
    logger.info(f"🔑 Initialisation Firebase avec l'environnement: {current_env} (fichier: {service_account_path})")
    
    if not os.path.exists(service_account_path):
        logger.error(f"serviceAccountKey.json introuvable: {service_account_path}")
        return None

    try:
        cred = credentials.Certificate(service_account_path)
        FIREBASE_APP = firebase_admin.initialize_app(cred)
        FIREBASE_APP_ENV = current_env
        logger.info(f"✅ App Firebase initialisée avec succès pour l'environnement: {current_env}")
    except ValueError:
        # App déjà initialisée ailleurs
        FIREBASE_APP = firebase_admin.get_app()
        FIREBASE_APP_ENV = current_env
        logger.info(f"✅ App Firebase récupérée (déjà initialisée) pour l'environnement: {current_env}")
    return FIREBASE_APP


def get_firestore_client(request=None):
    """
    Récupère le client Firestore
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    app = get_firebase_app(request)
    if not app:
        return None
    return firestore.client(app)


def fetch_firestore_users(request=None) -> Dict[str, dict]:
    """
    Récupère la collection users de Firestore (indexée par uid).
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Inclure l'environnement dans la clé de cache pour éviter les mélanges
    from .firebase_utils import get_firebase_env_from_session
    env = get_firebase_env_from_session(request)
    cache_key = f"{FIRESTORE_USERS_CACHE_KEY}_{env}"
    
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"📦 Firestore (cache): {len(cached)} utilisateurs")
        return cached

    client = get_firestore_client(request)
    if not client:
        return {}

    users_ref = client.collection('users')
    documents = users_ref.stream()
    firestore_users = {}
    for doc in documents:
        data = doc.to_dict() or {}
        uid = data.get('uid') or doc.id
        firestore_users[uid] = data
    logger.info(f"📦 Firestore: {len(firestore_users)} utilisateurs chargés")
    cache.set(cache_key, firestore_users, FIRESTORE_USERS_CACHE_TTL)
    return firestore_users


def fetch_auth_users(request=None) -> Dict[str, firebase_auth.UserRecord]:
    """
    Récupère les utilisateurs Firebase Auth.
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Inclure l'environnement dans la clé de cache
    from .firebase_utils import get_firebase_env_from_session
    env = get_firebase_env_from_session(request)
    cache_key = f"{AUTH_USERS_CACHE_KEY}_{env}"
    
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"🔐 Firebase Auth (cache): {len(cached)} utilisateurs")
        return cached

    app = get_firebase_app(request)
    if not app:
        return {}

    users = {}
    try:
        page = firebase_auth.list_users(app=app)
        for user in page.iterate_all():
            users[user.uid] = user
    except Exception as exc:
        logger.error(f"Erreur lors de la récupération des utilisateurs Firebase Auth: {exc}")
    logger.info(f"🔐 Firebase Auth: {len(users)} utilisateurs chargés")
    cache.set(cache_key, users, AUTH_USERS_CACHE_TTL)
    return users


def fetch_fcm_tokens(request=None) -> Dict[str, List[dict]]:
    """
    Récupère la collection fcm_tokens (indexée par userId).
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Inclure l'environnement dans la clé de cache
    from .firebase_utils import get_firebase_env_from_session
    env = get_firebase_env_from_session(request)
    cache_key = f"{FCM_TOKENS_CACHE_KEY}_{env}"
    
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"🔔 FCM tokens (cache): {len(cached)} utilisateurs avec token")
        return cached

    client = get_firestore_client(request)
    if not client:
        return {}

    tokens_ref = client.collection('fcm_tokens')
    documents = tokens_ref.stream()
    tokens_by_user = {}
    count = 0
    for doc in documents:
        data = doc.to_dict() or {}
        user_id = data.get('userId')
        if not user_id:
            continue
        tokens_by_user.setdefault(user_id, []).append(data)
        count += 1
    logger.info(f"🔔 FCM tokens chargés: {count} tokens pour {len(tokens_by_user)} utilisateurs")
    cache.set(cache_key, tokens_by_user, FCM_TOKENS_CACHE_TTL)
    return tokens_by_user


def normalize_datetime(value) -> Optional[datetime]:
    """Convertit différents formats (Firestore, timestamp ms, ISO string) vers datetime UTC."""
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        # Firebase Auth renvoie des timestamps en millisecondes
        if value > 1e12:
            value = value / 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            cleaned = value.replace('Z', '+00:00')
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None
    return None


def format_datetime(dt: Optional[datetime]) -> str:
    if not dt:
        return '—'
    local_dt = django_timezone.localtime(dt)
    return local_dt.strftime('%d/%m/%Y %H:%M')


def build_display_name(profile: dict, auth_user: Optional[firebase_auth.UserRecord]) -> str:
    candidates = [
        profile.get('name'),
        profile.get('nom'),
        profile.get('fullname'),
        profile.get('full_name'),
    ]
    if profile.get('prenom') or profile.get('nom'):
        candidates.append(f"{profile.get('prenom', '')} {profile.get('nom', '')}".strip())
    if auth_user:
        candidates.append(auth_user.display_name)
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return "Utilisateur sans nom"


def determine_connection_state(last_sign_in: Optional[datetime]) -> Tuple[str, str]:
    """Retourne (label, classe_css) selon l'activité récente."""
    if not last_sign_in:
        return "Jamais connecté", "bg-[#F1EFEB] text-[#535353] border border-[#C9C1B1]"

    now = django_timezone.now()
    delta = now - django_timezone.make_aware(last_sign_in) if last_sign_in.tzinfo is None else now - last_sign_in

    if delta <= timedelta(minutes=ONLINE_THRESHOLD_MINUTES):
        return "En ligne", "bg-[#D4F2DA] text-[#60BC81] border border-[#60BC81]"
    if delta <= timedelta(days=RECENT_THRESHOLD_DAYS):
        return "Actif récemment", "bg-[#F1EFEB] text-[#535353] border border-[#C9C1B1]"
    return "Inactif", "bg-[#F1EFEB] text-[#535353] border border-[#C9C1B1]"


def extract_phone(profile: dict, auth_user: Optional[firebase_auth.UserRecord]) -> Optional[str]:
    for key in ('phone', 'phoneNumber', 'telephone', 'tel'):
        value = profile.get(key)
        if value:
            return value
    if auth_user and auth_user.phone_number:
        return auth_user.phone_number
    return None


def extract_email(profile: dict, auth_user: Optional[firebase_auth.UserRecord]) -> Optional[str]:
    email = profile.get('email') or profile.get('mail')
    if email:
        return email
    if auth_user and auth_user.email:
        return auth_user.email
    return None


def extract_created_at(profile: dict, auth_user: Optional[firebase_auth.UserRecord]) -> Optional[datetime]:
    created = profile.get('createdAt') or profile.get('created_at')
    dt = normalize_datetime(created)
    if dt:
        return dt
    if auth_user and auth_user.user_metadata and auth_user.user_metadata.creation_timestamp:
        return normalize_datetime(auth_user.user_metadata.creation_timestamp / 1000)
    return None


def get_last_sign_in(auth_user: Optional[firebase_auth.UserRecord]) -> Optional[datetime]:
    if not auth_user or not auth_user.user_metadata:
        return None
    timestamp = auth_user.user_metadata.last_sign_in_timestamp
    if timestamp:
        return normalize_datetime(timestamp / 1000)
    return None


def merge_users_data(force_refresh=False, request=None) -> List[dict]:
    """
    Fusionne les données Firestore, Auth et FCM avec cache optimisé.
    
    Args:
        force_refresh: Forcer le rafraîchissement du cache
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    # Inclure l'environnement dans la clé de cache
    from .firebase_utils import get_firebase_env_from_session
    env = get_firebase_env_from_session(request)
    cache_key = f"{MERGE_USERS_CACHE_KEY}_{env}"
    
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info(f"📊 Utilisateurs fusionnés (cache): {len(cached)} utilisateurs")
            return cached

    firestore_users = fetch_firestore_users(request)
    auth_users = fetch_auth_users(request)
    fcm_tokens = fetch_fcm_tokens(request)

    combined = []
    handled_uids = set()

    for uid, auth_user in auth_users.items():
        profile = firestore_users.get(uid, {})
        combined.append(build_user_entry(uid, profile, auth_user, fcm_tokens))
        handled_uids.add(uid)

    # Ajouter les utilisateurs Firestore sans compte Auth
    for uid, profile in firestore_users.items():
        if uid not in handled_uids:
            combined.append(build_user_entry(uid, profile, None, fcm_tokens))

    logger.info(f"📊 Utilisateurs fusionnés: {len(combined)} total")

    combined.sort(key=lambda u: (u['display_name'] or '').lower())
    
    # Mettre en cache pour 10 minutes
    cache.set(cache_key, combined, MERGE_USERS_CACHE_TTL)
    
    return combined


def build_user_entry(
    uid: str,
    profile: dict,
    auth_user: Optional[firebase_auth.UserRecord],
    fcm_tokens_by_user: Dict[str, List[dict]],
) -> dict:
    phone = extract_phone(profile, auth_user)
    last_sign_in = get_last_sign_in(auth_user)
    connection_label, connection_class = determine_connection_state(last_sign_in)

    created_at = extract_created_at(profile, auth_user)
    birthdate = profile.get('dateNaissance') or profile.get('birthdate')
    display_name = build_display_name(profile, auth_user)
    email = extract_email(profile, auth_user)

    tokens = fcm_tokens_by_user.get(uid, [])

    return {
        'uid': uid,
        'display_name': display_name,
        'email': email,
        'phone': phone,
        'created_at': created_at,
        'created_at_display': format_datetime(created_at),
        'last_sign_in': last_sign_in,
        'last_sign_in_display': format_datetime(last_sign_in),
        'connection_label': connection_label,
        'connection_class': connection_class,
        'birthdate': birthdate,
        'fcm_tokens': tokens,
        'has_fcm_token': len(tokens) > 0,
        'fcm_tokens_count': len(tokens),
        'has_auth': auth_user is not None,
        'has_profile': bool(profile),
        'search_index': " ".join(filter(None, [
            uid,
            display_name,
            email,
            phone,
            birthdate,
        ])).lower(),
    }


def filter_users(users: List[dict], query: str, status: str) -> List[dict]:
    filtered = users
    if query:
        q = query.lower()
        filtered = [u for u in filtered if q in (u['search_index'] or '')]
    # Le filtre par status est supprimé car il était basé sur RevenueCat
    return filtered


def compute_status_metrics(users: List[dict]) -> dict:
    """Calcule les métriques globales des utilisateurs."""
    counts = {
        'total': len(users),
        'active': 0,
        'trial': 0,
        'grace': 0,
        'expired': 0,
        'none': 0,
        'online': 0,
        'tokens_total': 0,
    }
    
    # Pour les métriques qui nécessitent les données en mémoire (online, tokens)
    for user in users:
        if user['connection_label'] == 'En ligne':
            counts['online'] += 1
        counts['tokens_total'] += user.get('fcm_tokens_count', 0) or 0
    
    return counts


def build_query_without_page(request):
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    return query_params.urlencode()


@login_required
def users_list(request):
    """Page principale listant les utilisateurs avec recherche et filtres (optimisé)."""
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')
    page_number = request.GET.get('page', 1)
    force_refresh = request.GET.get('refresh') == '1'

    # Utiliser le cache sauf si refresh explicite
    users = merge_users_data(force_refresh=force_refresh, request=request)
    
    # Filtrer d'abord, puis paginer (plus efficace)
    filtered_users = filter_users(users, query, status_filter)
    filtered_count = len(filtered_users)
    
    # Pagination optimisée
    paginator = Paginator(filtered_users, USERS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    
    # Calculer les métriques uniquement si nécessaire (ou depuis le cache)
    metrics = compute_status_metrics(users)
    base_query = build_query_without_page(request)

    context = {
        'users': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'metrics': metrics,
        'results_count': filtered_count,
        'query_string': base_query,
        'status_options': [
            ('all', 'Tous'),
        ]
    }
    
    return render(request, 'scripts_manager/users/list.html', context)
