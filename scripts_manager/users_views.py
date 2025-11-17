"""
Vues pour la gestion et l'exploration des utilisateurs Firebase / RevenueCat
"""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import firebase_admin
import requests
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone as django_timezone
from django.contrib.auth.decorators import login_required
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, firestore

from config import SERVICE_ACCOUNT_PATH

logger = logging.getLogger(__name__)

FIREBASE_APP = None
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
RC_STATUS_CACHE_PREFIX = 'rc_status_cache::'
RC_STATUS_CACHE_TTL = int(os.getenv('REVENUECAT_STATUS_CACHE_TTL', 1800))
RC_MAX_CALLS_PER_VIEW = int(os.getenv('REVENUECAT_MAX_CALLS_PER_VIEW', 200))
USERS_PAGE_SIZE = int(os.getenv('USERS_PAGE_SIZE', 50))


def get_firebase_app():
    """Initialise (si nécessaire) et retourne l'app Firebase Admin."""
    global FIREBASE_APP
    if FIREBASE_APP:
        return FIREBASE_APP

    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        logger.error(f"serviceAccountKey.json introuvable: {SERVICE_ACCOUNT_PATH}")
        return None

    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        FIREBASE_APP = firebase_admin.initialize_app(cred)
    except ValueError:
        # App déjà initialisée ailleurs
        FIREBASE_APP = firebase_admin.get_app()
    return FIREBASE_APP


def get_firestore_client():
    app = get_firebase_app()
    if not app:
        return None
    return firestore.client(app)


def fetch_firestore_users() -> Dict[str, dict]:
    """Récupère la collection users de Firestore (indexée par uid)."""
    cached = cache.get(FIRESTORE_USERS_CACHE_KEY)
    if cached is not None:
        logger.info(f"📦 Firestore (cache): {len(cached)} utilisateurs")
        return cached

    client = get_firestore_client()
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
    cache.set(FIRESTORE_USERS_CACHE_KEY, firestore_users, FIRESTORE_USERS_CACHE_TTL)
    return firestore_users


def fetch_auth_users() -> Dict[str, firebase_auth.UserRecord]:
    """Récupère les utilisateurs Firebase Auth."""
    cached = cache.get(AUTH_USERS_CACHE_KEY)
    if cached is not None:
        logger.info(f"🔐 Firebase Auth (cache): {len(cached)} utilisateurs")
        return cached

    app = get_firebase_app()
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
    cache.set(AUTH_USERS_CACHE_KEY, users, AUTH_USERS_CACHE_TTL)
    return users


def fetch_fcm_tokens() -> Dict[str, List[dict]]:
    """Récupère la collection fcm_tokens (indexée par userId)."""
    cached = cache.get(FCM_TOKENS_CACHE_KEY)
    if cached is not None:
        logger.info(f"🔔 FCM tokens (cache): {len(cached)} utilisateurs avec token")
        return cached

    client = get_firestore_client()
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
    cache.set(FCM_TOKENS_CACHE_KEY, tokens_by_user, FCM_TOKENS_CACHE_TTL)
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


def default_revenuecat_status(reason: str = "none") -> dict:
    return {
        'status': 'none',
        'status_label': 'Gratuit',
        'status_class': 'badge-light',
        'expires_at': None,
        'period_type': None,
        'product_identifier': None,
        'will_renew': False,
        'is_sandbox': False,
        'reason': reason,
    }


class RevenueCatClient:
    BASE_URL = os.getenv('REVENUECAT_BASE_URL', 'https://api.revenuecat.com/v1')

    def __init__(self):
        self.api_key = (
            os.getenv('REVENUECAT_SECRET_KEY')
            or os.getenv('REVENUECAT_API_KEY')
            or os.getenv('RC_API_KEY')
        )
        self.session = requests.Session()
        self.calls_done = 0
        self.max_calls = RC_MAX_CALLS_PER_VIEW
        self.status_cache_ttl = RC_STATUS_CACHE_TTL
        if not self.api_key:
            logger.warning("Clé API RevenueCat manquante. Les statuts premium resteront inactifs.")

    def _hash_phone(self, phone: str) -> str:
        return hashlib.sha256(phone.encode('utf-8')).hexdigest()

    def _parse_rc_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
        except ValueError:
            return None

    def get_status(self, phone_number: Optional[str]) -> dict:
        if not self.api_key:
            return default_revenuecat_status("missing_api_key")
        if not phone_number:
            return default_revenuecat_status("missing_phone")

        app_user_id = self._hash_phone(phone_number)
        cache_key = f"{RC_STATUS_CACHE_PREFIX}{app_user_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if self.calls_done >= self.max_calls:
            throttled = default_revenuecat_status("quota_exceeded")
            throttled['note'] = 'Quota atteint, réessayez plus tard.'
            return throttled

        url = f"{self.BASE_URL}/subscribers/{app_user_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        try:
            response = self.session.get(url, headers=headers, timeout=10)
        except requests.RequestException as exc:
            logger.error(f"Erreur RevenueCat pour {phone_number}: {exc}")
            status = default_revenuecat_status("request_error")
            status['error'] = str(exc)
            return status

        if response.status_code == 404:
            return default_revenuecat_status("not_found")
        if response.status_code >= 400:
            logger.error(f"Erreur RevenueCat ({response.status_code}): {response.text}")
            status = default_revenuecat_status("api_error")
            status['error'] = response.text
            return status

        self.calls_done += 1

        data = response.json()
        subscriber = data.get('subscriber', {})
        entitlements = subscriber.get('entitlements', {})
        entitlement_name, entitlement = self._select_entitlement(entitlements)
        if not entitlement:
            return default_revenuecat_status("no_entitlement")

        expires_at = self._parse_rc_datetime(entitlement.get('expires_date'))
        grace_expires = self._parse_rc_datetime(entitlement.get('grace_period_expires_date'))
        now = django_timezone.now()
        product_id = entitlement.get('product_identifier')
        
        # Chercher period_type dans l'entitlement, puis dans les subscriptions du subscriber
        period_type = (entitlement.get('period_type') or '').lower()
        if not period_type:
            # Chercher dans les subscriptions actives
            subscriptions = subscriber.get('subscriptions', {})
            for sub_key, sub_data in subscriptions.items():
                if sub_data.get('product_identifier') == product_id:
                    period_type = (sub_data.get('period_type') or '').lower()
                    break
        
        will_renew = entitlement.get('will_renew', False)
        is_active = entitlement.get('is_active', False)
        
        # Vérifier aussi dans les subscriptions si is_active n'est pas défini
        if not is_active and product_id:
            subscriptions = subscriber.get('subscriptions', {})
            for sub_key, sub_data in subscriptions.items():
                if sub_data.get('product_identifier') == product_id:
                    is_active = sub_data.get('is_active', False)
                    break
        
        status_key = 'none'

        # Priorité 1: Grace period
        if grace_expires and grace_expires > now:
            status_key = 'grace'
        # Priorité 2: Trial (vérifier period_type ET que l'entitlement est actif/valide)
        elif period_type == 'trial':
            # Un trial est actif si expires_at est dans le futur ou n'existe pas
            if not expires_at or expires_at > now:
                status_key = 'trial'
            else:
                # Trial expiré -> considéré comme expired
                status_key = 'expired'
        # Priorité 3: Active subscription (pas un trial, mais actif)
        elif is_active or (expires_at and expires_at > now):
            # Si period_type n'est pas 'trial' et que c'est actif, c'est une subscription active
            status_key = 'active'
        # Priorité 4: Expired
        elif expires_at and expires_at <= now:
            status_key = 'expired'
        # Sinon: none (pas d'entitlement valide)

        # Log DÉTAILLÉ pour tous les statuts premium/trial/active/grace
        if status_key in ['active', 'trial', 'grace'] or period_type == 'trial' or is_active:
            logger.info("=" * 80)
            logger.info(f"📊 REVENUECAT STATUS DÉTAILLÉ - Téléphone: {phone_number}")
            logger.info(f"   App User ID (hash): {app_user_id}")
            logger.info(f"   Entitlement sélectionné: {entitlement_name}")
            logger.info(f"   Period Type: {period_type}")
            logger.info(f"   Is Active: {is_active}")
            logger.info(f"   Will Renew: {will_renew}")
            logger.info(f"   Expires At: {expires_at}")
            logger.info(f"   Grace Period Expires: {grace_expires}")
            logger.info(f"   Product Identifier: {entitlement.get('product_identifier')}")
            logger.info(f"   Is Sandbox: {entitlement.get('is_sandbox', False)}")
            logger.info(f"   STATUT DÉTECTÉ: {status_key}")
            logger.info(f"   Tous les entitlements disponibles: {list(entitlements.keys())}")
            logger.info(f"   Données complètes de l'entitlement: {entitlement}")
            logger.info(f"   Subscriptions disponibles: {list(subscriber.get('subscriptions', {}).keys())}")
            logger.info(f"   Données complètes du subscriber: {subscriber}")
            logger.info("=" * 80)

        status_map = {
            'active': ('Premium actif', 'bg-[#D4F2DA] text-[#60BC81] border border-[#60BC81]'),
            'trial': ('Essai en cours', 'bg-[#D4F2DA] text-[#60BC81] border border-[#60BC81]'),
            'grace': ('Grace period', 'bg-[#F1EFEB] text-[#535353] border border-[#C9C1B1]'),
            'expired': ('Abonnement expiré', 'bg-[#F2D7D4] text-[#D3695E] border border-[#D3695E]'),
            'none': ('Gratuit', 'bg-[#F1EFEB] text-[#535353] border border-[#C9C1B1]'),
        }
        label, css = status_map[status_key]

        status_payload = {
            'status': status_key,
            'status_label': label,
            'status_class': css,
            'expires_at': expires_at,
            'period_type': period_type.upper() if period_type else None,
            'product_identifier': entitlement.get('product_identifier'),
            'will_renew': will_renew,
            'is_sandbox': entitlement.get('is_sandbox', False),
            'entitlement': entitlement_name,
            'original_data': data,
        }
        
        # Log le statut final détecté
        if status_key in ['active', 'trial', 'grace']:
            logger.info(f"✅ STATUT FINAL DÉTECTÉ pour {phone_number[:5]}...: {status_key} ({label})")
        
        cache.set(cache_key, status_payload, self.status_cache_ttl)
        return status_payload

    @staticmethod
    def _select_entitlement(entitlements: dict) -> Tuple[Optional[str], Optional[dict]]:
        if not entitlements:
            return None, None
        if 'premium' in entitlements:
            return 'premium', entitlements['premium']
        # Sinon prendre le premier actif, sinon le premier
        for name, data in entitlements.items():
            if data.get('is_active') or data.get('expires_date'):
                return name, data
        first_key = next(iter(entitlements))
        return first_key, entitlements[first_key]


def merge_users_data(force_refresh=False) -> List[dict]:
    """Fusionne les données Firestore, Auth, FCM et RevenueCat avec cache optimisé."""
    if not force_refresh:
        cached = cache.get(MERGE_USERS_CACHE_KEY)
        if cached is not None:
            logger.info(f"📊 Utilisateurs fusionnés (cache): {len(cached)} utilisateurs")
            return cached

    firestore_users = fetch_firestore_users()
    auth_users = fetch_auth_users()
    fcm_tokens = fetch_fcm_tokens()
    rc_client = RevenueCatClient()

    combined = []
    handled_uids = set()
    users_with_phone = 0
    users_without_phone = 0
    rc_calls_made = 0

    for uid, auth_user in auth_users.items():
        profile = firestore_users.get(uid, {})
        phone = extract_phone(profile, auth_user)
        if phone:
            users_with_phone += 1
        else:
            users_without_phone += 1
        combined.append(build_user_entry(uid, profile, auth_user, rc_client, fcm_tokens))
        handled_uids.add(uid)

    # Ajouter les utilisateurs Firestore sans compte Auth
    for uid, profile in firestore_users.items():
        if uid not in handled_uids:
            phone = extract_phone(profile, None)
            if phone:
                users_with_phone += 1
            else:
                users_without_phone += 1
            combined.append(build_user_entry(uid, profile, None, rc_client, fcm_tokens))

    rc_calls_made = rc_client.calls_done
    
    # Log des statistiques
    logger.info(f"📊 Utilisateurs fusionnés: {len(combined)} total, {users_with_phone} avec téléphone, {users_without_phone} sans téléphone")
    logger.info(f"📞 Appels RevenueCat effectués: {rc_calls_made}/{rc_client.max_calls}")
    
    # Compter les statuts pour debug
    status_counts = {}
    for user in combined:
        status = user['rc_status']['status']
        status_counts[status] = status_counts.get(status, 0) + 1
    logger.info(f"📈 Répartition des statuts RevenueCat: {status_counts}")

    combined.sort(key=lambda u: (u['display_name'] or '').lower())
    
    # Mettre en cache pour 10 minutes
    cache.set(MERGE_USERS_CACHE_KEY, combined, MERGE_USERS_CACHE_TTL)
    
    return combined


def build_user_entry(
    uid: str,
    profile: dict,
    auth_user: Optional[firebase_auth.UserRecord],
    rc_client: RevenueCatClient,
    fcm_tokens_by_user: Dict[str, List[dict]],
) -> dict:
    phone = extract_phone(profile, auth_user)
    rc_status = rc_client.get_status(phone)
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
        'rc_status': rc_status,
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
    if status and status != 'all':
        filtered = [u for u in filtered if u['rc_status']['status'] == status]
    return filtered


def compute_status_metrics(users: List[dict]) -> dict:
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
    for user in users:
        status = user['rc_status']['status']
        if status in counts:
            counts[status] += 1
        else:
            counts['none'] += 1
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
    users = merge_users_data(force_refresh=force_refresh)
    
    # Filtrer d'abord, puis paginer (plus efficace)
    filtered_users = filter_users(users, query, status_filter)
    filtered_count = len(filtered_users)
    
    # Pagination optimisée
    paginator = Paginator(filtered_users, USERS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    
    # Calculer les métriques uniquement si nécessaire (ou depuis le cache)
    metrics = compute_status_metrics(users)
    base_query = build_query_without_page(request)

    revenuecat_enabled = bool(os.getenv('REVENUECAT_SECRET_KEY') or os.getenv('REVENUECAT_API_KEY') or os.getenv('RC_API_KEY'))

    context = {
        'users': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'metrics': metrics,
        'results_count': filtered_count,
        'query_string': base_query,
        'revenuecat_enabled': revenuecat_enabled,
        'status_options': [
            ('all', 'Tous'),
            ('active', 'Premium'),
            ('trial', 'Essai'),
            ('grace', 'Grace period'),
            ('expired', 'Expirés'),
            ('none', 'Gratuits'),
        ]
    }
    return render(request, 'scripts_manager/users/list.html', context)


@login_required
def refresh_user_status(request, uid):
    """API simple pour recharger le statut RevenueCat d'un utilisateur spécifique."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    phone = request.POST.get('phone')
    rc_client = RevenueCatClient()
    # Forcer le refresh en invalidant le cache
    app_user_id = rc_client._hash_phone(phone)
    cache_key = f"{RC_STATUS_CACHE_PREFIX}{app_user_id}"
    cache.delete(cache_key)
    
    status = rc_client.get_status(phone)
    payload = status.copy()
    expires = payload.get('expires_at')
    if isinstance(expires, datetime):
        payload['expires_at'] = expires.isoformat()
    return JsonResponse({'status': payload})


@login_required
def users_diagnostics(request):
    """Endpoint de diagnostic pour analyser les problèmes de mapping RevenueCat"""
    firestore_users = fetch_firestore_users()
    auth_users = fetch_auth_users()
    fcm_tokens = fetch_fcm_tokens()
    
    diagnostics = {
        'total_firestore_users': len(firestore_users),
        'total_auth_users': len(auth_users),
        'total_fcm_tokens': sum(len(tokens) for tokens in fcm_tokens.values()),
        'users_with_phone': 0,
        'users_without_phone': 0,
        'phone_numbers': [],
        'status_breakdown': {
            'active': 0,
            'trial': 0,
            'grace': 0,
            'expired': 0,
            'none': 0,
            'quota_exceeded': 0,
            'missing_phone': 0,
            'missing_api_key': 0,
        },
        'rc_calls_made': 0,
        'rc_max_calls': RC_MAX_CALLS_PER_VIEW,
    }
    
    rc_client = RevenueCatClient()
    
    # Analyser tous les utilisateurs
    all_uids = set(firestore_users.keys()) | set(auth_users.keys())
    for uid in all_uids:
        profile = firestore_users.get(uid, {})
        auth_user = auth_users.get(uid)
        phone = extract_phone(profile, auth_user)
        
        if phone:
            diagnostics['users_with_phone'] += 1
            diagnostics['phone_numbers'].append(phone[:10] + '...')  # Masquer pour la sécurité
            status = rc_client.get_status(phone)
            status_key = status.get('status', 'none')
            reason = status.get('reason', '')
            
            if status_key in diagnostics['status_breakdown']:
                diagnostics['status_breakdown'][status_key] += 1
            else:
                diagnostics['status_breakdown']['none'] += 1
            
            if reason == 'quota_exceeded':
                diagnostics['status_breakdown']['quota_exceeded'] += 1
            elif reason == 'missing_phone':
                diagnostics['status_breakdown']['missing_phone'] += 1
            elif reason == 'missing_api_key':
                diagnostics['status_breakdown']['missing_api_key'] += 1
        else:
            diagnostics['users_without_phone'] += 1
            diagnostics['status_breakdown']['missing_phone'] += 1
    
    diagnostics['rc_calls_made'] = rc_client.calls_done
    diagnostics['phone_numbers'] = diagnostics['phone_numbers'][:20]  # Limiter à 20 pour l'affichage
    
    return JsonResponse(diagnostics, json_dumps_params={'indent': 2})


@login_required
def users_log_all_premium(request):
    """Endpoint pour forcer le refresh et logger tous les statuts premium/trial/active"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    logger.info("=" * 100)
    logger.info("🔄 FORCE REFRESH - Logging de tous les statuts premium/trial/active")
    logger.info("=" * 100)
    
    # Vider le cache RevenueCat
    cache_pattern = f"{RC_STATUS_CACHE_PREFIX}*"
    # Django cache ne supporte pas les patterns, on doit vider manuellement
    # On va juste forcer le refresh pour chaque utilisateur
    
    firestore_users = fetch_firestore_users()
    auth_users = fetch_auth_users()
    
    rc_client = RevenueCatClient()
    rc_client.calls_done = 0  # Reset counter
    
    premium_users = []
    trial_users = []
    active_users = []
    
    all_uids = set(firestore_users.keys()) | set(auth_users.keys())
    logger.info(f"📊 Total utilisateurs à vérifier: {len(all_uids)}")
    
    for uid in all_uids:
        profile = firestore_users.get(uid, {})
        auth_user = auth_users.get(uid)
        phone = extract_phone(profile, auth_user)
        
        if phone:
            # Invalider le cache pour forcer le refresh
            app_user_id = rc_client._hash_phone(phone)
            cache_key = f"{RC_STATUS_CACHE_PREFIX}{app_user_id}"
            cache.delete(cache_key)
            
            # Récupérer le statut (va logger automatiquement)
            status = rc_client.get_status(phone)
            status_key = status.get('status', 'none')
            
            user_info = {
                'uid': uid,
                'phone': phone[:5] + '...',
                'name': profile.get('prenom', '') or auth_user.get('display_name', '') or 'N/A',
                'status': status_key,
                'status_label': status.get('status_label', ''),
            }
            
            if status_key == 'active':
                active_users.append(user_info)
            elif status_key == 'trial':
                trial_users.append(user_info)
            elif status_key == 'grace':
                premium_users.append(user_info)
    
    logger.info("=" * 100)
    logger.info(f"📈 RÉSUMÉ:")
    logger.info(f"   Premium actifs: {len(active_users)}")
    logger.info(f"   Trials: {len(trial_users)}")
    logger.info(f"   Grace period: {len(premium_users)}")
    logger.info(f"   Appels RevenueCat effectués: {rc_client.calls_done}")
    logger.info("=" * 100)
    
    return JsonResponse({
        'success': True,
        'summary': {
            'active': len(active_users),
            'trial': len(trial_users),
            'grace': len(premium_users),
            'rc_calls': rc_client.calls_done,
        },
        'active_users': active_users[:50],  # Limiter à 50
        'trial_users': trial_users[:50],
        'premium_users': premium_users[:50],
    }, json_dumps_params={'indent': 2})

