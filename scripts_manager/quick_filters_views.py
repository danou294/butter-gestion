"""
Views pour la gestion des Quick Filters dans le backoffice Django.
Écrit directement dans Firestore (collection 'quick_filters').
Compatible dev/prod via get_firestore_client(request).
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)
from .restaurants_views import get_firestore_client

# Valeurs possibles pour chaque catégorie de filtre
# Doivent correspondre EXACTEMENT aux valeurs utilisées dans l'app Flutter (SearchService)
FILTER_OPTIONS = {
    'zones': ['Ouest', 'Centre', 'Est'],
    'moments': ['Petit-déjeuner', 'Brunch', 'Déjeuner', 'Goûter', 'Drinks', 'Dîner'],
    'cuisines': ['Italien', 'Méditerranéen', 'Asiatique', 'Français', 'Sud-Américain', 'Indien', 'Américain', 'Africain'],
    'prix': ['€', '€€', '€€€', '€€€€'],
    'lieux': ['Bar', 'Cave à manger', 'Coffee shop', 'Fast', 'Brasserie', 'Hôtel', 'Gastronomique'],
    'ambiance': ['Entre amis', 'En famille', 'Date', 'Festif'],
    'restrictions': ['Casher', '100% végétarien', 'Healthy'],
}

BOOLEAN_FILTERS = ['openNow', 'noReservation', 'hasTerrace', 'hasPrivateRoom']

BOOLEAN_LABELS = {
    'openNow': 'Ouvert maintenant',
    'noReservation': 'Sans réservation',
    'hasTerrace': 'Terrasse',
    'hasPrivateRoom': 'Salle privatisable',
}


def _count_active_filters(data):
    """Compte le nombre de paramètres de filtre actifs dans un quick filter."""
    count = 0
    filters = data.get('filters', {})
    for key in FILTER_OPTIONS:
        if filters.get(key):
            count += len(filters[key])
    for key in BOOLEAN_FILTERS:
        if filters.get(key):
            count += 1
    return count


# ==================== LISTE ====================

@login_required
def quick_filters_list(request):
    """Affiche la liste de tous les quick filters."""
    try:
        db = get_firestore_client(request)
        docs = db.collection('quick_filters').get()

        quick_filters = []
        active_count = 0

        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            data['filter_count'] = _count_active_filters(data)
            quick_filters.append(data)
            if data.get('isActive'):
                active_count += 1

        # Tri par createdAt desc
        quick_filters.sort(
            key=lambda x: x.get('createdAt') or datetime.min,
            reverse=True,
        )

        context = {
            'quick_filters': quick_filters,
            'total_count': len(quick_filters),
            'active_count': active_count,
        }
        return render(request, 'scripts_manager/quick_filters/list.html', context)

    except Exception as e:
        logger.exception("[quick_filters_list] Erreur: %s", e)
        messages.error(request, f"Erreur lors du chargement : {str(e)}")
        return render(request, 'scripts_manager/quick_filters/list.html', {
            'quick_filters': [],
            'total_count': 0,
            'active_count': 0,
        })


# ==================== CRÉER ====================

@login_required
def quick_filter_create(request):
    """Formulaire de création d'un quick filter."""
    if request.method == 'POST':
        try:
            db = get_firestore_client(request)

            title = request.POST.get('title', '').strip()
            subtitle = request.POST.get('subtitle', '').strip()
            is_active = request.POST.get('isActive') == 'on'

            if not title or not subtitle:
                messages.error(request, "Le titre et le sous-titre sont requis")
                return render(request, 'scripts_manager/quick_filters/form.html', {
                    'form_data': request.POST,
                    'mode': 'create',
                    'filter_options': FILTER_OPTIONS,
                    'boolean_filters': BOOLEAN_FILTERS,
                    'boolean_labels': BOOLEAN_LABELS,
                })

            # Construire l'objet filters depuis les checkboxes
            filters_data = {}
            for key in FILTER_OPTIONS:
                filters_data[key] = request.POST.getlist(key)
            for key in BOOLEAN_FILTERS:
                filters_data[key] = request.POST.get(key) == 'on'

            doc_data = {
                'title': title,
                'subtitle': subtitle,
                'isActive': is_active,
                'filters': filters_data,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
            }

            doc_ref = db.collection('quick_filters').add(doc_data)
            # .add() retourne un tuple (timestamp, doc_ref)
            new_id = doc_ref[1].id

            messages.success(request, f"Quick filter '{title}' créé avec succès !")
            return redirect('scripts_manager:quick_filters_list')

        except Exception as e:
            logger.exception("[quick_filter_create] Erreur: %s", e)
            messages.error(request, f"Erreur lors de la création : {str(e)}")
            return render(request, 'scripts_manager/quick_filters/form.html', {
                'form_data': request.POST,
                'mode': 'create',
                'filter_options': FILTER_OPTIONS,
                'boolean_filters': BOOLEAN_FILTERS,
                'boolean_labels': BOOLEAN_LABELS,
            })

    # GET
    return render(request, 'scripts_manager/quick_filters/form.html', {
        'mode': 'create',
        'filter_options': FILTER_OPTIONS,
        'boolean_filters': BOOLEAN_FILTERS,
        'boolean_labels': BOOLEAN_LABELS,
    })


# ==================== ÉDITER ====================

@login_required
def quick_filter_edit(request, filter_id):
    """Formulaire d'édition d'un quick filter."""
    db = get_firestore_client(request)
    doc_ref = db.collection('quick_filters').document(filter_id)

    if request.method == 'POST':
        try:
            doc = doc_ref.get()
            if not doc.exists:
                messages.error(request, f"Quick filter '{filter_id}' non trouvé")
                return redirect('scripts_manager:quick_filters_list')

            title = request.POST.get('title', '').strip()
            subtitle = request.POST.get('subtitle', '').strip()
            is_active = request.POST.get('isActive') == 'on'

            if not title or not subtitle:
                messages.error(request, "Le titre et le sous-titre sont requis")
                return redirect('scripts_manager:quick_filter_edit', filter_id=filter_id)

            filters_data = {}
            for key in FILTER_OPTIONS:
                filters_data[key] = request.POST.getlist(key)
            for key in BOOLEAN_FILTERS:
                filters_data[key] = request.POST.get(key) == 'on'

            update_data = {
                'title': title,
                'subtitle': subtitle,
                'isActive': is_active,
                'filters': filters_data,
                'updatedAt': datetime.utcnow(),
            }

            doc_ref.update(update_data)

            messages.success(request, f"Quick filter '{title}' mis à jour !")
            return redirect('scripts_manager:quick_filters_list')

        except Exception as e:
            logger.exception("[quick_filter_edit] Erreur: %s", e)
            messages.error(request, f"Erreur lors de la mise à jour : {str(e)}")
            return redirect('scripts_manager:quick_filter_edit', filter_id=filter_id)

    # GET
    try:
        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Quick filter '{filter_id}' non trouvé")
            return redirect('scripts_manager:quick_filters_list')

        qf_data = doc.to_dict()
        qf_data['id'] = filter_id

        context = {
            'quick_filter': qf_data,
            'filter_id': filter_id,
            'mode': 'edit',
            'filter_options': FILTER_OPTIONS,
            'boolean_filters': BOOLEAN_FILTERS,
            'boolean_labels': BOOLEAN_LABELS,
        }
        return render(request, 'scripts_manager/quick_filters/form.html', context)

    except Exception as e:
        logger.exception("[quick_filter_edit] Erreur chargement: %s", e)
        messages.error(request, f"Erreur lors du chargement : {str(e)}")
        return redirect('scripts_manager:quick_filters_list')


# ==================== SUPPRIMER ====================

@login_required
@require_http_methods(["POST"])
def quick_filter_delete(request, filter_id):
    """Supprime un quick filter."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection('quick_filters').document(filter_id)

        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Quick filter '{filter_id}' non trouvé")
            return redirect('scripts_manager:quick_filters_list')

        title = doc.to_dict().get('title', filter_id)
        doc_ref.delete()

        messages.success(request, f"Quick filter '{title}' supprimé")
        return redirect('scripts_manager:quick_filters_list')

    except Exception as e:
        logger.exception("[quick_filter_delete] Erreur: %s", e)
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
        return redirect('scripts_manager:quick_filters_list')


# ==================== JSON ====================

@login_required
def quick_filter_get_json(request, filter_id):
    """Retourne le JSON d'un quick filter."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection('quick_filters').document(filter_id)
        doc = doc_ref.get()

        if not doc.exists:
            return JsonResponse({'error': 'Quick filter non trouvé'}, status=404)

        data = doc.to_dict()
        data['id'] = doc.id

        for key in ['createdAt', 'updatedAt']:
            if key in data and data[key]:
                val = data[key]
                data[key] = val.isoformat() if hasattr(val, 'isoformat') else str(val)

        return JsonResponse(data, json_dumps_params={'indent': 2, 'ensure_ascii': False})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
