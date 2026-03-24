"""
Views pour la configuration dynamique des paywalls.
Collection Firestore : paywall_config
Document : dismiss_feedback
"""

import json
import logging

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .restaurants_views import get_firestore_client

logger = logging.getLogger(__name__)

COLLECTION = 'paywall_config'
DOC_ID = 'dismiss_feedback'

DEFAULT_DATA = {
    'title': "Tu n'es pas intéressé ?",
    'subtitle': 'Explique-nous pourquoi',
    'closeLabel': 'Fermer',
    'reasons': [
        "J'aurais payé 9,99€/mois",
        "J'ai d'abord besoin d'essayer",
        "J'ai besoin de plus d'informations",
        "Je ne paye pas pour des apps",
    ],
}


@login_required
def paywall_config_manage(request):
    """Page de gestion du paywall dismiss feedback."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(COLLECTION).document(DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
        else:
            data = dict(DEFAULT_DATA)

        return render(request, 'scripts_manager/paywall_config/manage.html', {
            'config_json': json.dumps(data, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur chargement paywall_config: {e}")
        messages.error(request, f"Erreur : {e}")
        return render(request, 'scripts_manager/paywall_config/manage.html', {
            'config_json': json.dumps(DEFAULT_DATA, ensure_ascii=False),
        })


@login_required
@require_http_methods(["POST"])
def paywall_config_save(request):
    """Sauvegarde le document dismiss_feedback dans Firestore."""
    try:
        raw = request.POST.get('config_data', '{}')
        data = json.loads(raw)

        title = (data.get('title') or '').strip()
        subtitle = (data.get('subtitle') or '').strip()
        close_label = (data.get('closeLabel') or '').strip()
        reasons = data.get('reasons', [])

        if not title:
            messages.error(request, "Le titre est obligatoire.")
            return redirect('scripts_manager:paywall_config_manage')

        # Nettoyer les raisons vides
        clean_reasons = [r.strip() for r in reasons if r and r.strip()]

        if not clean_reasons:
            messages.error(request, "Il faut au moins une raison.")
            return redirect('scripts_manager:paywall_config_manage')

        doc_data = {
            'title': title,
            'subtitle': subtitle,
            'closeLabel': close_label,
            'reasons': clean_reasons,
        }

        db = get_firestore_client(request)
        db.collection(COLLECTION).document(DOC_ID).set(doc_data)

        messages.success(request, "Configuration paywall sauvegardée.")
    except json.JSONDecodeError:
        messages.error(request, "Données invalides.")
    except Exception as e:
        logger.error(f"Erreur sauvegarde paywall_config: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:paywall_config_manage')


@login_required
@require_http_methods(["POST"])
def paywall_config_reset(request):
    """Remet les valeurs par défaut."""
    try:
        db = get_firestore_client(request)
        db.collection(COLLECTION).document(DOC_ID).set(DEFAULT_DATA)
        messages.success(request, "Configuration réinitialisée aux valeurs par défaut.")
    except Exception as e:
        logger.error(f"Erreur reset paywall_config: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:paywall_config_manage')
