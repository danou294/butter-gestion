"""
Vues Django pour le dashboard RevenueCat et la gestion des statuts abonnements.
"""
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.paginator import Paginator

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
def subscribers_list(request):
    """Liste des utilisateurs avec un abonnement RevenueCat (depuis la DB)."""
    from .models import RevenueCatUserStatus
    from .users_views import merge_users_data

    status_filter = request.GET.get('status', 'all')
    query = request.GET.get('q', '').strip()
    page_number = request.GET.get('page', 1)

    # Récupérer les statuts RC depuis la DB
    qs = RevenueCatUserStatus.objects.all().order_by('-updated_at')

    if status_filter == 'active':
        qs = qs.filter(is_active=True, is_sandbox=False)
    elif status_filter == 'trial':
        qs = qs.filter(period_type='trial', is_active=True)
    elif status_filter == 'expired':
        qs = qs.filter(status='expired')
    elif status_filter == 'sandbox':
        qs = qs.filter(is_sandbox=True)

    # Enrichir avec les données Firebase (noms, emails)
    firebase_users = {}
    try:
        all_users = merge_users_data(request=request)
        for u in all_users:
            firebase_users[u['uid']] = u
    except Exception as e:
        logger.warning(f"Impossible de charger les users Firebase: {e}")

    subscribers = []
    for rc in qs:
        fb_user = firebase_users.get(rc.uid, {})
        display_name = fb_user.get('display_name', '') or ''
        email = fb_user.get('email', '') or ''

        # Filtre recherche
        if query:
            q_lower = query.lower()
            searchable = f"{display_name} {email} {rc.phone} {rc.uid} {rc.product_identifier or ''}".lower()
            if q_lower not in searchable:
                continue

        subscribers.append({
            'uid': rc.uid,
            'display_name': display_name or 'Utilisateur sans nom',
            'email': email,
            'phone': rc.phone,
            'status': rc.status,
            'status_label': rc.status_label,
            'is_active': rc.is_active,
            'is_sandbox': rc.is_sandbox,
            'product_identifier': rc.product_identifier or '',
            'period_type': rc.period_type or '',
            'expires_at': rc.expires_at,
            'purchase_date': rc.purchase_date,
            'will_renew': rc.will_renew,
            'updated_at': rc.updated_at,
        })

    total_count = len(subscribers)
    paginator = Paginator(subscribers, 50)
    page_obj = paginator.get_page(page_number)

    # Métriques rapides
    all_rc = RevenueCatUserStatus.objects.all()
    metrics = {
        'total': all_rc.count(),
        'active': all_rc.filter(is_active=True, is_sandbox=False).exclude(period_type='trial').count(),
        'trial': all_rc.filter(period_type='trial', is_active=True).count(),
        'expired': all_rc.filter(status='expired').count(),
        'sandbox': all_rc.filter(is_sandbox=True).count(),
    }

    scan_progress = rc_service.get_scan_progress()
    is_scanning = rc_service.is_scan_running()

    context = {
        'subscribers': page_obj.object_list,
        'page_obj': page_obj,
        'results_count': total_count,
        'query': query,
        'status_filter': status_filter,
        'metrics': metrics,
        'scan_progress': scan_progress,
        'is_scanning': is_scanning,
        'status_options': [
            ('all', 'Tous'),
            ('active', 'Actifs'),
            ('trial', 'Essais'),
            ('expired', 'Expirés'),
            ('sandbox', 'Sandbox'),
        ],
    }
    return render(request, 'scripts_manager/users/subscribers.html', context)


@login_required
def refresh_all_revenuecat(request):
    """Lance un scan complet de tous les users Firebase → RevenueCat."""
    redirect_to = request.GET.get('next', 'scripts_manager:dashboard_revenuecat')

    if rc_service.is_scan_running():
        messages.warning(request, "Un scan est déjà en cours. Veuillez patienter.")
    else:
        started = rc_service.start_scan_background(request)
        if started:
            messages.success(request, "Scan RevenueCat lancé en arrière-plan.")
        else:
            messages.error(request, "Impossible de démarrer le scan.")

    return redirect(redirect_to)


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
        messages.warning(request, "Pas de numéro de téléphone. Impossible de récupérer les données RevenueCat.")
        return redirect('scripts_manager:user_detail', uid=uid)

    status = rc_service.get_user_rc_status(uid, phone)
    if status:
        rc_service.save_rc_status_to_db(uid, phone, status)
        messages.success(request, f"Données RevenueCat mises à jour : {status['status_label']}")
    else:
        messages.info(request, "Aucun abonnement RevenueCat trouvé pour cet utilisateur.")

    return redirect('scripts_manager:user_detail', uid=uid)
