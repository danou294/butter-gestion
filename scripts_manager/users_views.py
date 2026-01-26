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
from google.api_core import exceptions as gcp_exceptions

from config import SERVICE_ACCOUNT_PATH, EXPORTS_DIR
from .firebase_utils import get_service_account_path

logger = logging.getLogger(__name__)

FIREBASE_APP = None
FIREBASE_APP_ENV = None  # Stocker l'environnement utilisé pour l'app
ONLINE_THRESHOLD_MINUTES = 15
RECENT_THRESHOLD_DAYS = 7

USERS_CACHE_KEY = 'users_merged_cache_v1'
MERGE_USERS_CACHE_KEY = 'merged_users_cache_v1'
MERGE_USERS_CACHE_TTL = int(os.getenv('MERGE_USERS_CACHE_TTL', 1800))  # 30 minutes (augmenté pour éviter les quotas)
USERS_CACHE_TTL = int(os.getenv('USERS_CACHE_TTL', os.getenv('CACHE_TTL', 180)))
FIRESTORE_USERS_CACHE_KEY = 'firestore_users_cache_v1'
FIRESTORE_USERS_CACHE_TTL = int(os.getenv('FIRESTORE_USERS_CACHE_TTL', 1800))  # 30 minutes (augmenté)
AUTH_USERS_CACHE_KEY = 'firebase_auth_users_cache_v1'
AUTH_USERS_CACHE_TTL = int(os.getenv('AUTH_USERS_CACHE_TTL', 1800))  # 30 minutes (augmenté)
FCM_TOKENS_CACHE_KEY = 'fcm_tokens_cache_v1'
FCM_TOKENS_CACHE_TTL = int(os.getenv('FCM_TOKENS_CACHE_TTL', 1800))  # 30 minutes (augmenté)
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
    logger.info("🔍 [fetch_firestore_users] Début de la fonction")
    # Inclure l'environnement dans la clé de cache pour éviter les mélanges
    from .firebase_utils import get_firebase_env_from_session
    from google.api_core import exceptions as gcp_exceptions
    env = get_firebase_env_from_session(request)
    logger.info(f"🌍 [fetch_firestore_users] Environnement: {env}")
    cache_key = f"{FIRESTORE_USERS_CACHE_KEY}_{env}"
    logger.info(f"🔑 [fetch_firestore_users] Clé de cache: {cache_key}")
    
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"📦 [fetch_firestore_users] Cache trouvé: {len(cached)} utilisateurs")
        return cached
    logger.info("❌ [fetch_firestore_users] Pas de cache, récupération depuis Firestore")

    logger.info("🔧 [fetch_firestore_users] Récupération du client Firestore...")
    client = get_firestore_client(request)
    if not client:
        logger.error("❌ [fetch_firestore_users] Pas de client Firestore disponible")
        return {}
    logger.info("✅ [fetch_firestore_users] Client Firestore obtenu")

    try:
        logger.info("📚 [fetch_firestore_users] Accès à la collection 'users'...")
        users_ref = client.collection('users')
        # Limiter le nombre de documents pour éviter les quotas (max 200 en DEV)
        max_users = 200 if env == 'dev' else 1000
        logger.info(f"📊 [fetch_firestore_users] Limite: {max_users} utilisateurs")
        
        logger.info("🔄 [fetch_firestore_users] Exécution de la requête Firestore (stream avec itération manuelle)...")
        # Utiliser limit() pour éviter de charger trop de données
        # Itérer manuellement pour éviter les blocages avec list()
        documents = []
        stream = users_ref.limit(max_users).stream()
        count = 0
        max_iterations = max_users + 10  # Limite de sécurité
        
        try:
            logger.info("🔄 [fetch_firestore_users] Début de l'itération sur le stream...")
            for doc in stream:
                count += 1
                if count % 10 == 0:
                    logger.info(f"📊 [fetch_firestore_users] {count} documents traités...")
                if count > max_users:
                    logger.warning(f"⚠️  [fetch_firestore_users] Limite de {max_users} atteinte, arrêt")
                    break
                documents.append(doc)
                if count >= max_iterations:
                    logger.warning(f"⚠️  [fetch_firestore_users] Limite de sécurité {max_iterations} atteinte, arrêt")
                    break
            logger.info(f"✅ [fetch_firestore_users] Itération terminée: {count} documents parcourus")
        except gcp_exceptions.ResourceExhausted as quota_error:
            logger.error(f"❌ [fetch_firestore_users] Quota dépassé lors du stream: {quota_error}")
            # Si on a déjà récupéré des documents, on les utilise
            if documents:
                logger.warning(f"⚠️  [fetch_firestore_users] Utilisation de {len(documents)} documents déjà récupérés malgré le quota")
            else:
                raise
        except Exception as stream_error:
            logger.error(f"❌ [fetch_firestore_users] Erreur lors du stream: {type(stream_error).__name__}: {stream_error}", exc_info=True)
            # Si on a déjà récupéré des documents, on les utilise
            if documents:
                logger.warning(f"⚠️  [fetch_firestore_users] Utilisation de {len(documents)} documents déjà récupérés")
            else:
                raise
        
        logger.info(f"✅ [fetch_firestore_users] {len(documents)} documents récupérés depuis Firestore")
        
        firestore_users = {}
        logger.info("🔄 [fetch_firestore_users] Traitement des documents...")
        for doc in documents:
            data = doc.to_dict() or {}
            uid = data.get('uid') or doc.id
            firestore_users[uid] = data
        
        logger.info(f"📦 [fetch_firestore_users] {len(firestore_users)} utilisateurs traités")
        logger.info(f"💾 [fetch_firestore_users] Mise en cache pour {FIRESTORE_USERS_CACHE_TTL}s...")
        cache.set(cache_key, firestore_users, FIRESTORE_USERS_CACHE_TTL)
        logger.info("✅ [fetch_firestore_users] Cache mis à jour")
        return firestore_users
    except gcp_exceptions.ResourceExhausted as e:
        logger.error(f"❌ Quota Firebase dépassé lors de la récupération des utilisateurs: {e}")
        # Essayer de récupérer le cache même s'il est expiré
        expired_cache = cache.get(cache_key)
        if expired_cache is not None:
            logger.warning(f"⚠️  Utilisation du cache expiré en raison du quota dépassé")
            return expired_cache
        logger.error(f"❌ Aucun cache disponible, retour d'une liste vide")
        return {}
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des utilisateurs Firestore: {type(e).__name__}: {e}")
        # Essayer de récupérer le cache même s'il est expiré
        expired_cache = cache.get(cache_key)
        if expired_cache is not None:
            logger.warning(f"⚠️  Utilisation du cache expiré en raison d'une erreur")
            return expired_cache
        logger.error(f"❌ Aucun cache disponible, retour d'une liste vide")
        return {}


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
        logger.info("🔄 [fetch_auth_users] Appel à list_users()...")
        page = firebase_auth.list_users(app=app)
        logger.info("🔄 [fetch_auth_users] Itération sur les utilisateurs...")
        for user in page.iterate_all():
            users[user.uid] = user
        logger.info(f"✅ [fetch_auth_users] {len(users)} utilisateurs récupérés")
    except Exception as exc:
        logger.error(f"❌ [fetch_auth_users] Erreur lors de la récupération: {type(exc).__name__}: {exc}", exc_info=True)
    logger.info(f"🔐 [fetch_auth_users] {len(users)} utilisateurs chargés")
    logger.info(f"💾 [fetch_auth_users] Mise en cache pour {AUTH_USERS_CACHE_TTL}s...")
    cache.set(cache_key, users, AUTH_USERS_CACHE_TTL)
    logger.info("✅ [fetch_auth_users] Cache mis à jour")
    return users


def fetch_fcm_tokens(request=None) -> Dict[str, List[dict]]:
    """
    Récupère la collection fcm_tokens (indexée par userId).
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    logger.info("🔍 [fetch_fcm_tokens] Début de la fonction")
    # Inclure l'environnement dans la clé de cache
    from .firebase_utils import get_firebase_env_from_session
    env = get_firebase_env_from_session(request)
    logger.info(f"🌍 [fetch_fcm_tokens] Environnement: {env}")
    cache_key = f"{FCM_TOKENS_CACHE_KEY}_{env}"
    
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(f"🔔 [fetch_fcm_tokens] Cache trouvé: {len(cached)} utilisateurs avec token")
        return cached
    logger.info("❌ [fetch_fcm_tokens] Pas de cache, récupération depuis Firestore")

    logger.info("🔧 [fetch_fcm_tokens] Récupération du client Firestore...")
    client = get_firestore_client(request)
    if not client:
        logger.error("❌ [fetch_fcm_tokens] Pas de client Firestore disponible")
        return {}

    logger.info("📚 [fetch_fcm_tokens] Accès à la collection 'fcm_tokens'...")
    tokens_ref = client.collection('fcm_tokens')
    logger.info("🔄 [fetch_fcm_tokens] Exécution de la requête Firestore (stream)...")
    documents = tokens_ref.stream()
    tokens_by_user = {}
    count = 0
    logger.info("🔄 [fetch_fcm_tokens] Traitement des documents...")
    for doc in documents:
        count += 1
        data = doc.to_dict() or {}
        user_id = data.get('userId')
        if not user_id:
            continue
        tokens_by_user.setdefault(user_id, []).append(data)
    logger.info(f"✅ [fetch_fcm_tokens] {count} documents traités, {len(tokens_by_user)} utilisateurs avec token")
    logger.info(f"💾 [fetch_fcm_tokens] Mise en cache pour {FCM_TOKENS_CACHE_TTL}s...")
    cache.set(cache_key, tokens_by_user, FCM_TOKENS_CACHE_TTL)
    logger.info("✅ [fetch_fcm_tokens] Cache mis à jour")
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
    
    logger.info(f"🔄 [merge_users_data] Début - force_refresh={force_refresh}, env={env}")
    
    if not force_refresh:
        logger.info(f"🔍 [merge_users_data] Vérification du cache...")
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info(f"📊 [merge_users_data] Cache trouvé: {len(cached)} utilisateurs")
            return cached
        logger.info("❌ [merge_users_data] Pas de cache valide")

    # En DEV, privilégier le cache même expiré pour éviter les quotas
    if env == 'dev':
        logger.info("🔍 [merge_users_data] Mode DEV: vérification du cache expiré...")
        expired_cache = cache.get(cache_key)
        if expired_cache is not None and not force_refresh:
            logger.warning(f"⚠️  [merge_users_data] Mode DEV: utilisation du cache même expiré pour éviter les quotas")
            return expired_cache
        logger.info("❌ [merge_users_data] Pas de cache expiré disponible")

    try:
        logger.info("📥 [merge_users_data] Récupération des données Firestore...")
        firestore_users = fetch_firestore_users(request)
        logger.info(f"✅ [merge_users_data] Firestore: {len(firestore_users)} utilisateurs")
        
        logger.info("📥 [merge_users_data] Récupération des données Auth...")
        auth_users = fetch_auth_users(request)
        logger.info(f"✅ [merge_users_data] Auth: {len(auth_users)} utilisateurs")
        
        logger.info("📥 [merge_users_data] Récupération des tokens FCM...")
        fcm_tokens = fetch_fcm_tokens(request)
        logger.info(f"✅ [merge_users_data] FCM: {len(fcm_tokens)} utilisateurs avec tokens")
    except Exception as e:
        logger.error(f"❌ [merge_users_data] Erreur lors de la récupération des données utilisateurs: {type(e).__name__}: {e}", exc_info=True)
        # En cas d'erreur, retourner le cache même s'il est expiré
        logger.info("🔍 [merge_users_data] Tentative de récupération du cache expiré...")
        expired_cache = cache.get(cache_key)
        if expired_cache is not None:
            logger.warning(f"⚠️  [merge_users_data] Utilisation du cache expiré en raison d'une erreur: {len(expired_cache)} utilisateurs")
            return expired_cache
        # Si pas de cache, retourner une liste vide plutôt que de planter
        logger.error(f"❌ [merge_users_data] Aucun cache disponible, retour d'une liste vide")
        return []

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
    logger.info("=" * 80)
    logger.info("🚀 [users_list] DÉBUT de la vue users_list")
    logger.info("=" * 80)
    
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')
    page_number = request.GET.get('page', 1)
    force_refresh = request.GET.get('refresh') == '1'
    
    logger.info(f"📋 [users_list] Paramètres: query='{query}', status='{status_filter}', page={page_number}, refresh={force_refresh}")

    # Utiliser le cache sauf si refresh explicite
    error_message = None
    try:
        logger.info("🔄 [users_list] Appel à merge_users_data...")
        users = merge_users_data(force_refresh=force_refresh, request=request)
        logger.info(f"✅ [users_list] merge_users_data terminé: {len(users)} utilisateurs")
    except Exception as e:
        logger.error(f"❌ [users_list] Erreur lors de la récupération des utilisateurs: {type(e).__name__}: {e}", exc_info=True)
        # En cas d'erreur, retourner une liste vide plutôt que de planter
        users = []
        error_message = f"Erreur lors du chargement des utilisateurs: {type(e).__name__}. Les données en cache sont affichées si disponibles."
    
    logger.info(f"🔄 [users_list] Filtrage des utilisateurs...")
    # Filtrer d'abord, puis paginer (plus efficace)
    filtered_users = filter_users(users, query, status_filter)
    filtered_count = len(filtered_users)
    logger.info(f"✅ [users_list] {filtered_count} utilisateurs après filtrage")
    
    logger.info(f"🔄 [users_list] Pagination...")
    # Pagination optimisée
    paginator = Paginator(filtered_users, USERS_PAGE_SIZE)
    try:
        page_obj = paginator.get_page(page_number)
    except Exception:
        page_obj = paginator.get_page(1)
    logger.info(f"✅ [users_list] Page {page_obj.number}/{paginator.num_pages} avec {len(page_obj.object_list)} utilisateurs")
    
    logger.info(f"🔄 [users_list] Calcul des métriques...")
    # Calculer les métriques uniquement si nécessaire (ou depuis le cache)
    metrics = compute_status_metrics(users)
    base_query = build_query_without_page(request)
    logger.info(f"✅ [users_list] Métriques calculées: {metrics}")

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
        ],
        'error_message': error_message,
    }
    
    logger.info("=" * 80)
    logger.info("✅ [users_list] FIN de la vue users_list - Rendu du template")
    logger.info("=" * 80)
    
    return render(request, 'scripts_manager/users/list.html', context)
