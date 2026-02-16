"""
Service RevenueCat — API V2 (overview metrics) + V1 (per-user subscriber data).

L'app Butter utilise SHA256(numéro_de_téléphone) comme app_user_id RevenueCat.
Ce module gère :
- API V2 : métriques dashboard (MRR, active subs, trials, revenue, etc.)
- API V1 : données par subscriber (statut, produit, expiration, etc.)
- Le scan de tous les users Firebase pour récupérer leur statut RC individuel
"""
import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────
REVENUECAT_API_KEY_V1 = os.getenv('REVENUECAT_API_KEY', '')
REVENUECAT_API_KEY_V2 = os.getenv('REVENUECAT_API_KEY_V2', '')
REVENUECAT_PROJECT_ID = 'proj4d1b1dce'  # Butter

RC_V1_URL = 'https://api.revenuecat.com/v1/subscribers'
RC_V2_URL = 'https://api.revenuecat.com/v2'

BATCH_SIZE = 10
BATCH_DELAY = 1.1  # RC rate limit ~10 req/s

# Cache
RC_DASHBOARD_CACHE_KEY = 'revenuecat_dashboard_v2'
RC_DASHBOARD_CACHE_TTL = 600  # 10 minutes

# Scan state (thread-safe)
_scan_lock = threading.Lock()
_scan_running = False
_scan_progress = {'current': 0, 'total': 0, 'started_at': None, 'status': 'idle'}


# ─── API V2 : Overview Metrics ───────────────────────────────────────────────

def fetch_overview_metrics_v2() -> Optional[dict]:
    """
    Appelle l'API RevenueCat V2 /metrics/overview.
    Retourne les métriques directement depuis RC (source de vérité).
    """
    if not REVENUECAT_API_KEY_V2:
        logger.warning("REVENUECAT_API_KEY_V2 non définie, fallback sur V1")
        return None

    url = f"{RC_V2_URL}/projects/{REVENUECAT_PROJECT_ID}/metrics/overview"
    headers = {
        'Authorization': f'Bearer {REVENUECAT_API_KEY_V2}',
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.error(f"RC V2 overview: HTTP {resp.status_code}")
            return None

        data = resp.json()
        metrics_list = data.get('metrics', [])

        # Parser les métriques en dict
        result = {}
        for m in metrics_list:
            result[m['id']] = {
                'value': m['value'],
                'name': m['name'],
                'description': m['description'],
                'unit': m.get('unit', ''),
                'period': m.get('period', ''),
            }

        return result

    except requests.RequestException as e:
        logger.error(f"Erreur API RC V2 overview: {e}")
        return None


def compute_dashboard_metrics() -> dict:
    """
    Récupère les métriques dashboard.
    Priorité : API V2 (temps réel) > Cache > Calcul depuis DB (V1 scan).
    """
    cached = cache.get(RC_DASHBOARD_CACHE_KEY)
    if cached:
        return cached

    # Essayer l'API V2 d'abord
    v2_metrics = fetch_overview_metrics_v2()
    if v2_metrics:
        metrics = {
            'active_trials': v2_metrics.get('active_trials', {}).get('value', 0),
            'active_subscriptions': v2_metrics.get('active_subscriptions', {}).get('value', 0),
            'mrr': v2_metrics.get('mrr', {}).get('value', 0),
            'revenue_28_days': v2_metrics.get('revenue', {}).get('value', 0),
            'new_customers_28_days': v2_metrics.get('new_customers', {}).get('value', 0),
            'active_customers': v2_metrics.get('active_users', {}).get('value', 0),
            'transactions_28_days': v2_metrics.get('num_tx_last_28_days', {}).get('value', 0),
            'source': 'revenuecat_v2',
            'last_updated': datetime.now(timezone.utc).isoformat(),
        }
        cache.set(RC_DASHBOARD_CACHE_KEY, metrics, RC_DASHBOARD_CACHE_TTL)
        return metrics

    # Fallback : calcul depuis la DB (données du scan V1)
    logger.info("V2 indisponible, fallback sur les données DB")
    return _compute_metrics_from_db()


def _compute_metrics_from_db() -> dict:
    """Calcule les métriques depuis les données stockées en DB (via scan V1)."""
    from .models import RevenueCatUserStatus

    now = datetime.now(timezone.utc)
    all_statuses = RevenueCatUserStatus.objects.all()

    active_trials = 0
    active_subscriptions = 0
    active_customers = 0

    for s in all_statuses:
        is_active = s.is_active and s.expires_at and s.expires_at > now
        is_sandbox = s.is_sandbox or s.is_sandbox_entitlement
        if not is_active or is_sandbox:
            continue
        active_customers += 1
        if s.period_type == 'trial':
            active_trials += 1
        else:
            active_subscriptions += 1

    metrics = {
        'active_trials': active_trials,
        'active_subscriptions': active_subscriptions,
        'mrr': 0,
        'revenue_28_days': 0,
        'new_customers_28_days': 0,
        'active_customers': active_customers,
        'transactions_28_days': 0,
        'source': 'database_scan',
        'last_updated': now.isoformat(),
    }

    cache.set(RC_DASHBOARD_CACHE_KEY, metrics, RC_DASHBOARD_CACHE_TTL)
    return metrics


# ─── API V1 : Per-user subscriber data ───────────────────────────────────────

def phone_to_rc_id(phone: str) -> str:
    """Convertit un numéro de téléphone en app_user_id RevenueCat (SHA256)."""
    return hashlib.sha256(phone.encode()).hexdigest()


def fetch_rc_subscriber(app_user_id: str) -> Optional[dict]:
    """
    Appelle l'API RevenueCat V1 pour un subscriber.
    Retourne None si le subscriber n'existe pas (status 201 = créé vide).
    """
    if not REVENUECAT_API_KEY_V1:
        logger.error("REVENUECAT_API_KEY non définie")
        return None

    url = f"{RC_V1_URL}/{app_user_id}"
    headers = {
        'Authorization': f'Bearer {REVENUECAT_API_KEY_V1}',
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get('subscriber')
        return None
    except requests.RequestException as e:
        logger.warning(f"Erreur API RC V1 pour {app_user_id[:12]}...: {e}")
        return None


def parse_subscriber_status(subscriber_data: dict) -> dict:
    """Parse les données RC d'un subscriber en dict structuré."""
    now = datetime.now(timezone.utc)
    subs = subscriber_data.get('subscriptions', {})

    result = {
        'is_active': False,
        'is_trial': False,
        'is_sandbox': False,
        'status': 'none',
        'status_label': 'Gratuit',
        'product_identifier': None,
        'period_type': None,
        'expires_at': None,
        'purchase_date': None,
        'will_renew': False,
        'grace_period_expires_at': None,
        'store': None,
        'first_seen': subscriber_data.get('first_seen'),
        'last_seen': subscriber_data.get('last_seen'),
    }

    if not subs:
        return result

    # Trouver l'abonnement actif le plus récent
    best_sub = None
    best_product = None
    for product_id, sub in subs.items():
        expires = sub.get('expires_date')
        if not expires:
            continue
        try:
            exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            if exp_dt > now:
                if best_sub is None:
                    best_sub = sub
                    best_product = product_id
                else:
                    best_exp = datetime.fromisoformat(
                        best_sub['expires_date'].replace('Z', '+00:00')
                    )
                    if exp_dt > best_exp:
                        best_sub = sub
                        best_product = product_id
        except (ValueError, TypeError):
            pass

    # Si aucun actif, prendre le plus récent expiré
    if not best_sub:
        for product_id, sub in subs.items():
            expires = sub.get('expires_date')
            if not expires:
                continue
            if best_sub is None:
                best_sub = sub
                best_product = product_id
            else:
                try:
                    best_exp = datetime.fromisoformat(
                        (best_sub.get('expires_date') or '2000-01-01T00:00:00Z').replace('Z', '+00:00')
                    )
                    new_exp = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                    if new_exp > best_exp:
                        best_sub = sub
                        best_product = product_id
                except (ValueError, TypeError):
                    pass

    if not best_sub:
        return result

    result['product_identifier'] = best_product
    result['period_type'] = best_sub.get('period_type')
    result['is_sandbox'] = best_sub.get('is_sandbox', False)
    result['store'] = best_sub.get('store')
    result['will_renew'] = best_sub.get('unsubscribe_detected_at') is None

    for field, key in [
        ('expires_at', 'expires_date'),
        ('purchase_date', 'purchase_date'),
        ('grace_period_expires_at', 'grace_period_expires_date'),
    ]:
        val = best_sub.get(key)
        if val:
            try:
                result[field] = datetime.fromisoformat(val.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass

    # Déterminer le statut
    if result['expires_at'] and result['expires_at'] > now:
        result['is_active'] = True
        if result['period_type'] == 'trial':
            result['is_trial'] = True
            result['status'] = 'trial'
            result['status_label'] = 'Essai en cours'
        else:
            result['status'] = 'active'
            result['status_label'] = 'Premium actif'
    elif result['grace_period_expires_at'] and result['grace_period_expires_at'] > now:
        result['is_active'] = True
        result['status'] = 'grace'
        result['status_label'] = 'Période de grâce'
    else:
        result['status'] = 'expired'
        result['status_label'] = 'Abonnement expiré'

    return result


def get_user_rc_status(uid: str, phone: str) -> Optional[dict]:
    """Récupère le statut RevenueCat d'un utilisateur via son téléphone."""
    if not phone:
        return None

    rc_id = phone_to_rc_id(phone)
    subscriber = fetch_rc_subscriber(rc_id)
    if not subscriber:
        return None

    status = parse_subscriber_status(subscriber)
    status['rc_app_user_id'] = rc_id
    status['uid'] = uid
    status['phone'] = phone
    status['raw_data'] = subscriber
    return status


def save_rc_status_to_db(uid: str, phone: str, status: dict):
    """Sauvegarde le statut RC dans le model Django."""
    from .models import RevenueCatUserStatus

    rc_id = status.get('rc_app_user_id', phone_to_rc_id(phone))

    RevenueCatUserStatus.objects.update_or_create(
        uid=uid,
        defaults={
            'phone': phone,
            'app_user_id': rc_id,
            'status': status['status'],
            'status_label': status['status_label'],
            'is_active': status['is_active'],
            'is_sandbox': status.get('is_sandbox', False),
            'is_sandbox_entitlement': status.get('is_sandbox', False),
            'product_identifier': status.get('product_identifier'),
            'period_type': status.get('period_type'),
            'will_renew': status.get('will_renew', False),
            'expires_at': status.get('expires_at'),
            'purchase_date': status.get('purchase_date'),
            'grace_period_expires_at': status.get('grace_period_expires_at'),
            'raw_data': status.get('raw_data', {}),
        }
    )


# ─── Background scan (V1 per-user) ───────────────────────────────────────────

def get_scan_progress() -> dict:
    return _scan_progress.copy()


def is_scan_running() -> bool:
    return _scan_running


def start_scan_background(request=None):
    """Lance le scan en arrière-plan dans un thread."""
    if _scan_running:
        return False
    thread = threading.Thread(target=_run_scan, args=(request,), daemon=True)
    thread.start()
    return True


def _run_scan(request=None):
    """Scan complet : Firebase Auth → SHA256(phone) → RevenueCat V1 API."""
    global _scan_running, _scan_progress

    if _scan_running:
        return

    with _scan_lock:
        _scan_running = True
        _scan_progress = {
            'current': 0, 'total': 0,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'status': 'loading_users',
            'found_active': 0, 'found_total': 0,
        }

    try:
        from .users_views import fetch_auth_users, fetch_firestore_users, extract_phone

        auth_users = fetch_auth_users(request)
        firestore_users = fetch_firestore_users(request)

        # Collecter les users avec téléphone (dédupliquer)
        users_to_scan = []
        seen_phones = set()
        for uid, auth_user in auth_users.items():
            profile = firestore_users.get(uid, {})
            phone = extract_phone(profile, auth_user)
            if phone and phone not in seen_phones:
                users_to_scan.append({'uid': uid, 'phone': phone})
                seen_phones.add(phone)

        for uid, profile in firestore_users.items():
            if uid not in auth_users:
                phone = profile.get('phone') or profile.get('phoneNumber')
                if phone and phone not in seen_phones:
                    users_to_scan.append({'uid': uid, 'phone': phone})
                    seen_phones.add(phone)

        total = len(users_to_scan)
        logger.info(f"🔄 [RC Scan] {total} utilisateurs à scanner")
        _scan_progress.update({'total': total, 'status': 'scanning'})

        found_active = 0
        found_total = 0
        session = requests.Session()

        for i in range(0, total, BATCH_SIZE):
            batch = users_to_scan[i:i + BATCH_SIZE]
            for user in batch:
                rc_id = phone_to_rc_id(user['phone'])
                try:
                    resp = session.get(
                        f"{RC_V1_URL}/{rc_id}",
                        headers={
                            'Authorization': f'Bearer {REVENUECAT_API_KEY_V1}',
                            'Content-Type': 'application/json',
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        subscriber = resp.json().get('subscriber', {})
                        if subscriber.get('subscriptions') or subscriber.get('entitlements'):
                            status = parse_subscriber_status(subscriber)
                            status['rc_app_user_id'] = rc_id
                            status['raw_data'] = subscriber
                            save_rc_status_to_db(user['uid'], user['phone'], status)
                            found_total += 1
                            if status['is_active']:
                                found_active += 1
                except Exception as e:
                    logger.warning(f"Erreur RC scan {user['uid']}: {e}")

            _scan_progress.update({
                'current': min(i + BATCH_SIZE, total),
                'found_active': found_active,
                'found_total': found_total,
            })

            if i + BATCH_SIZE < total:
                time.sleep(BATCH_DELAY)

            done = min(i + BATCH_SIZE, total)
            if done % 100 == 0 or done == total:
                logger.info(f"🔄 [RC Scan] {done}/{total}, {found_active} actifs")

        session.close()
        cache.delete(RC_DASHBOARD_CACHE_KEY)

        _scan_progress.update({
            'current': total,
            'status': 'completed',
            'completed_at': datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"✅ [RC Scan] Terminé: {found_total} subscribers, {found_active} actifs")

    except Exception as e:
        logger.error(f"❌ [RC Scan] Erreur: {e}", exc_info=True)
        _scan_progress['status'] = f'error: {str(e)}'
    finally:
        _scan_running = False
