"""
Views pour la configuration des offerings de paywalls.
Collection Firestore : app_config / document : paywalls
"""

import json
import logging
from datetime import datetime

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .restaurants_views import get_firestore_client

logger = logging.getLogger(__name__)

COLLECTION = 'app_config'
DOC_ID = 'paywalls'

PLACEMENTS = [
    ('onboarding_1', 'Premier paywall de l\'onboarding'),
    ('onboarding_2', 'Deuxième paywall de l\'onboarding (après code invitation)'),
    ('in_app_default', 'Paywall par défaut dans l\'app'),
    ('swipe_limit', 'Paywall quand limite de swipes atteinte'),
    ('choose_limit', 'Paywall quand limite de choose atteinte'),
    ('spin_limit', 'Paywall quand limite de spin atteinte'),
    ('dismiss_feedback', 'Paywall réduit (quand l\'user dit "j\'aurais payé 9.99€")'),
    ('import_addresses', 'Paywall pour créer une collection (import)'),
    ('search_filter', 'Paywall pour les filtres premium de recherche'),
    ('guide_premium', 'Paywall pour accéder aux guides premium'),
]

DEFAULT_OFFERINGS = {
    'onboarding_1': 'Paywall 1 onboarding',
    'onboarding_2': 'Paywall 2 onboarding',
    'in_app_default': 'Paywall in app - 9.02',
    'swipe_limit': 'paywall_swipe',
    'choose_limit': 'paywall_choose',
    'spin_limit': 'paywall_spin',
    'dismiss_feedback': 'Premiumreduc',
    'import_addresses': 'Paywall in app - 9.02',
    'search_filter': 'Paywall in app - 9.02',
    'guide_premium': 'Paywall in app - 9.02',
}


@login_required
def paywall_offerings_manage(request):
    """Page de gestion des offerings de paywalls."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(COLLECTION).document(DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
            offerings = data.get('offerings', {})
        else:
            offerings = dict(DEFAULT_OFFERINGS)

        return render(request, 'scripts_manager/paywall_offerings/manage.html', {
            'offerings_json': json.dumps(offerings, ensure_ascii=False),
            'placements_json': json.dumps(PLACEMENTS, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur chargement paywall_offerings: {e}")
        messages.error(request, f"Erreur : {e}")
        return render(request, 'scripts_manager/paywall_offerings/manage.html', {
            'offerings_json': json.dumps(DEFAULT_OFFERINGS, ensure_ascii=False),
            'placements_json': json.dumps(PLACEMENTS, ensure_ascii=False),
        })


@login_required
@require_http_methods(["POST"])
def paywall_offerings_save(request):
    """Sauvegarde les offerings dans Firestore."""
    try:
        raw = request.POST.get('offerings_data', '{}')
        offerings = json.loads(raw)

        # Nettoyer
        clean = {}
        for key, _ in PLACEMENTS:
            val = (offerings.get(key) or '').strip()
            if val:
                clean[key] = val

        if not clean:
            messages.error(request, "Au moins un offering doit être renseigné.")
            return redirect('scripts_manager:paywall_offerings_manage')

        db = get_firestore_client(request)
        db.collection(COLLECTION).document(DOC_ID).set({
            'offerings': clean,
            'updatedAt': datetime.utcnow(),
        })

        messages.success(request, "Configuration paywalls sauvegardée.")
    except json.JSONDecodeError:
        messages.error(request, "Données invalides.")
    except Exception as e:
        logger.error(f"Erreur sauvegarde paywall_offerings: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:paywall_offerings_manage')


@login_required
@require_http_methods(["POST"])
def paywall_offerings_reset(request):
    """Remet les valeurs par défaut."""
    try:
        db = get_firestore_client(request)
        db.collection(COLLECTION).document(DOC_ID).set({
            'offerings': DEFAULT_OFFERINGS,
            'updatedAt': datetime.utcnow(),
        })
        messages.success(request, "Configuration réinitialisée aux valeurs par défaut.")
    except Exception as e:
        logger.error(f"Erreur reset paywall_offerings: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:paywall_offerings_manage')
