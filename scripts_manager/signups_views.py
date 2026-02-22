"""
Dashboard unifié — inscriptions Firebase + métriques RevenueCat.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .users_views import fetch_auth_users, fetch_firestore_users
from . import revenuecat_service as rc_service

logger = logging.getLogger(__name__)


def _detect_auth_method(auth_user, firestore_data):
    """
    Détecte la méthode d'authentification d'un utilisateur.
    Priorité : Firestore authProvider > Firebase Auth provider_data > phone_number > inconnu.
    """
    if firestore_data:
        provider = (firestore_data.get('authProvider') or '').lower()
        if provider in ('apple', 'google'):
            return provider

    if auth_user and auth_user.provider_data:
        provider_ids = [p.provider_id for p in auth_user.provider_data]
        if 'apple.com' in provider_ids:
            return 'apple'
        if 'google.com' in provider_ids:
            return 'google'
        if 'phone' in provider_ids:
            return 'phone'
        if 'password' in provider_ids:
            return 'email'

    if auth_user and auth_user.phone_number:
        return 'phone'

    return 'inconnu'


def _french_day_name(weekday):
    names = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    return names[weekday]


@login_required
def dashboard(request):
    """Dashboard unifié : inscriptions + RevenueCat."""

    # ── Dates (défaut : 7 derniers jours) ──
    today = datetime.now(timezone.utc).date()
    default_from = today - timedelta(days=6)

    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else default_from
    except ValueError:
        date_from = default_from

    try:
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else today
    except ValueError:
        date_to = today

    dt_from = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
    dt_to = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)

    # ── Inscriptions Firebase ──
    auth_users = fetch_auth_users(request)
    firestore_users = fetch_firestore_users(request)

    methods = ['phone', 'apple', 'google', 'email', 'inconnu']
    totals = {m: 0 for m in methods}
    daily = defaultdict(lambda: {m: 0 for m in methods})
    total_users_all_time = len(auth_users)

    for uid, auth_user in auth_users.items():
        creation_ts = getattr(auth_user.user_metadata, 'creation_timestamp', None)
        if creation_ts is None:
            continue

        created_at = datetime.fromtimestamp(creation_ts / 1000, tz=timezone.utc)
        if created_at < dt_from or created_at > dt_to:
            continue

        fs_data = firestore_users.get(uid)
        method = _detect_auth_method(auth_user, fs_data)

        totals[method] = totals.get(method, 0) + 1
        day_key = created_at.strftime('%Y-%m-%d')
        daily[day_key][method] = daily[day_key].get(method, 0) + 1

    total_signups = sum(totals.values())

    # Chart.js data
    chart_labels = []
    chart_data = {m: [] for m in methods}
    current = date_from
    while current <= date_to:
        day_str = current.strftime('%Y-%m-%d')
        chart_labels.append(current.strftime('%d/%m'))
        day_data = daily.get(day_str, {m: 0 for m in methods})
        for m in methods:
            chart_data[m].append(day_data.get(m, 0))
        current += timedelta(days=1)

    # Table rows
    table_rows = []
    current = date_from
    while current <= date_to:
        day_str = current.strftime('%Y-%m-%d')
        day_data = daily.get(day_str, {m: 0 for m in methods})
        day_total = sum(day_data.values())
        table_rows.append({
            'date': current.strftime('%d/%m/%Y'),
            'day_name': _french_day_name(current.weekday()),
            'total': day_total,
            **day_data,
        })
        current += timedelta(days=1)
    table_rows.reverse()

    # ── RevenueCat ──
    rc_metrics = {}
    try:
        rc_metrics = rc_service.compute_dashboard_metrics()
    except Exception as e:
        logger.warning(f"Erreur RevenueCat: {e}")

    context = {
        # Dates
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        # Inscriptions
        'total_signups': total_signups,
        'total_users_all_time': total_users_all_time,
        'totals': totals,
        'table_rows': table_rows,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_phone_json': json.dumps(chart_data['phone']),
        'chart_apple_json': json.dumps(chart_data['apple']),
        'chart_google_json': json.dumps(chart_data['google']),
        'chart_email_json': json.dumps(chart_data['email']),
        'chart_inconnu_json': json.dumps(chart_data['inconnu']),
        # RevenueCat
        'rc': rc_metrics,
    }
    return render(request, 'scripts_manager/signups/dashboard.html', context)
