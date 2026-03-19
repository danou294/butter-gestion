"""
Views pour la gestion des sections dynamiques de la page d'accueil.
Collection Firestore : home_sections
Chaque document = une section (titre + guideIds + ordre + taille + ville).
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

COLLECTION = 'home_sections'


@login_required
def home_sections_manage(request):
    """Page de gestion des sections de la home."""
    try:
        db = get_firestore_client(request)

        # Charger toutes les sections
        sections_docs = db.collection(COLLECTION).get()
        sections = []
        for doc in sections_docs:
            data = doc.to_dict()
            data['id'] = doc.id
            sections.append(data)

        sections.sort(key=lambda s: (s.get('city', ''), s.get('order', 999)))

        # Charger tous les guides pour le picker
        guides_docs = db.collection('guides').order_by('order').get()
        all_guides = []
        for gdoc in guides_docs:
            gdata = gdoc.to_dict()
            all_guides.append({
                'id': gdoc.id,
                'name': gdata.get('name', gdoc.id),
                'description': gdata.get('description', ''),
                'city': gdata.get('city', ''),
                'isPremium': gdata.get('isPremium', False),
                'restaurant_count': len(gdata.get('restaurantIds', [])),
            })

        context = {
            'sections': sections,
            'sections_json': json.dumps(sections, default=str),
            'all_guides': all_guides,
            'all_guides_json': json.dumps(all_guides, default=str),
            'total_count': len(sections),
            'active_count': sum(1 for s in sections if s.get('isActive', False)),
        }
        return render(request, 'scripts_manager/home_sections/manage.html', context)

    except Exception as e:
        logger.exception("Erreur home_sections_manage: %s", e)
        messages.error(request, f"Erreur : {str(e)}")
        return render(request, 'scripts_manager/home_sections/manage.html', {
            'sections': [], 'sections_json': '[]',
            'all_guides': [], 'all_guides_json': '[]',
            'total_count': 0, 'active_count': 0,
        })


@require_http_methods(["POST"])
@login_required
def home_sections_save(request):
    """Sauvegarde toutes les sections (JSON complet depuis le front Alpine.js)."""
    try:
        db = get_firestore_client(request)

        raw = request.POST.get('sections_data', '[]')
        sections_data = json.loads(raw)

        if not isinstance(sections_data, list):
            messages.error(request, "Données invalides")
            return redirect('scripts_manager:home_sections_manage')

        # Charger les IDs existants pour détecter les suppressions
        existing_docs = db.collection(COLLECTION).get()
        existing_ids = {doc.id for doc in existing_docs}
        new_ids = set()

        saved = 0
        for section in sections_data:
            title = (section.get('title') or '').strip()
            if not title:
                continue

            guide_ids = section.get('guideIds', [])
            if not isinstance(guide_ids, list):
                guide_ids = []
            guide_ids = [gid for gid in guide_ids if isinstance(gid, str) and gid.strip()]

            city = (section.get('city') or 'Paris').strip()
            order = int(section.get('order', 0) or 0)
            display_size = section.get('displaySize', 'small')
            if display_size not in ('small', 'large'):
                display_size = 'small'
            is_active = bool(section.get('isActive', True))

            doc_data = {
                'title': title,
                'guideIds': guide_ids,
                'order': order,
                'displaySize': display_size,
                'isActive': is_active,
                'city': city,
                'updatedAt': datetime.utcnow(),
            }

            section_id = section.get('id', '').strip()
            if section_id and section_id in existing_ids:
                # Update existant
                db.collection(COLLECTION).document(section_id).update(doc_data)
                new_ids.add(section_id)
            else:
                # Nouveau document
                doc_data['createdAt'] = datetime.utcnow()
                new_ref = db.collection(COLLECTION).add(doc_data)
                new_ids.add(new_ref[1].id)

            saved += 1

        # Supprimer les sections retirées
        deleted = 0
        for old_id in existing_ids - new_ids:
            db.collection(COLLECTION).document(old_id).delete()
            deleted += 1

        msg = f"{saved} section(s) sauvegardée(s)"
        if deleted:
            msg += f", {deleted} supprimée(s)"
        messages.success(request, msg)

    except json.JSONDecodeError:
        messages.error(request, "Erreur de format JSON")
    except Exception as e:
        logger.exception("Erreur home_sections_save: %s", e)
        messages.error(request, f"Erreur : {str(e)}")

    return redirect('scripts_manager:home_sections_manage')


@require_http_methods(["POST"])
@login_required
def home_sections_delete(request, section_id):
    """Supprime une section."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection(COLLECTION).document(section_id)
        doc = doc_ref.get()

        if not doc.exists:
            messages.error(request, f"Section '{section_id}' non trouvée")
        else:
            title = doc.to_dict().get('title', section_id)
            doc_ref.delete()
            messages.success(request, f"Section '{title}' supprimée")

    except Exception as e:
        logger.exception("Erreur home_sections_delete: %s", e)
        messages.error(request, f"Erreur : {str(e)}")

    return redirect('scripts_manager:home_sections_manage')
