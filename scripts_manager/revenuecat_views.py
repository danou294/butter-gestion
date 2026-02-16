"""
Vues Django pour le dashboard RevenueCat et la gestion des statuts abonnements.
"""
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages

from . import revenuecat_service as rc_service

logger = logging.getLogger(__name__)


@login_required
def dashboard_revenuecat(request):
    """Page dashboard avec métriques RevenueCat."""
    metrics = rc_service.compute_dashboard_metrics()
    scan_progress = rc_service.get_scan_progress()
    is_scanning = rc_service.is_scan_running()

    context = {
        'dashboard': metrics,
        'scan_progress': scan_progress,
        'is_scanning': is_scanning,
    }
    return render(request, 'scripts_manager/users/dashboard.html', context)


@login_required
def refresh_all_revenuecat(request):
    """Lance un scan complet de tous les users Firebase → RevenueCat."""
    if rc_service.is_scan_running():
        messages.warning(request, "Un scan est déjà en cours. Veuillez patienter.")
    else:
        started = rc_service.start_scan_background(request)
        if started:
            messages.success(request, "Scan RevenueCat lancé en arrière-plan. Les données seront mises à jour progressivement.")
        else:
            messages.error(request, "Impossible de démarrer le scan.")

    return redirect('scripts_manager:dashboard_revenuecat')


@login_required
def scan_status_api(request):
    """API JSON pour polling du statut du scan (AJAX)."""
    progress = rc_service.get_scan_progress()
    progress['is_running'] = rc_service.is_scan_running()
    return JsonResponse(progress)


@login_required
def user_refresh_revenuecat(request, uid):
    """Actualise les données RevenueCat d'un seul utilisateur."""
    from .users_views import fetch_auth_users, fetch_firestore_users, extract_phone

    auth_users = fetch_auth_users(request)
    firestore_users = fetch_firestore_users(request)

    auth_user = auth_users.get(uid)
    profile = firestore_users.get(uid, {})
    phone = extract_phone(profile, auth_user)

    if not phone:
        messages.warning(request, f"Pas de numéro de téléphone pour cet utilisateur. Impossible de récupérer les données RevenueCat.")
        return redirect('scripts_manager:user_detail', uid=uid)

    status = rc_service.get_user_rc_status(uid, phone)
    if status:
        rc_service.save_rc_status_to_db(uid, phone, status)
        messages.success(request, f"Données RevenueCat mises à jour : {status['status_label']}")
    else:
        messages.info(request, "Aucun abonnement RevenueCat trouvé pour cet utilisateur.")

    return redirect('scripts_manager:user_detail', uid=uid)
