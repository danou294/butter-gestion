"""
Views pour la gestion des sections dynamiques de la page d'accueil.
Collection Firestore : home_sections
Chaque document = une section avec un type (guides, videos, decide, guide_collections).
"""

import json
import logging
from datetime import datetime

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .restaurants_views import get_firestore_client
from .firebase_utils import get_firebase_bucket

logger = logging.getLogger(__name__)

COLLECTION = 'home_sections'
VALID_SECTION_TYPES = ('guides', 'videos', 'decide', 'guide_collections')


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
            'firebase_bucket': get_firebase_bucket(request),
        }
        return render(request, 'scripts_manager/home_sections/manage.html', context)

    except Exception as e:
        logger.exception("Erreur home_sections_manage: %s", e)
        messages.error(request, f"Erreur : {str(e)}")
        return render(request, 'scripts_manager/home_sections/manage.html', {
            'sections': [], 'sections_json': '[]',
            'all_guides': [], 'all_guides_json': '[]',
            'total_count': 0, 'active_count': 0,
            'firebase_bucket': get_firebase_bucket(request),
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

            section_type = section.get('type', 'guides')
            if section_type not in VALID_SECTION_TYPES:
                section_type = 'guides'

            city = (section.get('city') or 'Paris').strip()
            order = int(section.get('order', 0) or 0)
            is_active = bool(section.get('isActive', True))

            doc_data = {
                'title': title,
                'type': section_type,
                'order': order,
                'isActive': is_active,
                'city': city,
                'updatedAt': datetime.utcnow(),
            }

            # Padding (optionnel, nombre >= 0)
            for pad_field in ('topPadding', 'bottomPadding'):
                raw_val = section.get(pad_field)
                if raw_val is not None and raw_val != '' and raw_val is not False:
                    try:
                        val = float(raw_val)
                        if val >= 0:
                            doc_data[pad_field] = val
                    except (ValueError, TypeError):
                        pass

            # guideIds et displaySize uniquement pour le type "guides"
            if section_type == 'guides':
                guide_ids = section.get('guideIds', [])
                if not isinstance(guide_ids, list):
                    guide_ids = []
                guide_ids = [gid for gid in guide_ids if isinstance(gid, str) and gid.strip()]
                display_size = section.get('displaySize', 'small')
                if display_size not in ('small', 'large'):
                    display_size = 'small'
                doc_data['guideIds'] = guide_ids
                doc_data['displaySize'] = display_size

                # Layout overrides (optionnels, vide = fallback sur displaySize)
                # cardWidth/cardHeight (carousel home) et gridColumns/gridAspectRatio (page section)
                for fkey in ('cardWidth', 'cardHeight', 'gridAspectRatio'):
                    raw_val = section.get(fkey)
                    if raw_val is not None and raw_val != '' and raw_val is not False:
                        try:
                            val = float(raw_val)
                            if val > 0:
                                doc_data[fkey] = val
                        except (ValueError, TypeError):
                            pass
                raw_cols = section.get('gridColumns')
                if raw_cols is not None and raw_cols != '' and raw_cols is not False:
                    try:
                        val = int(raw_cols)
                        if val > 0:
                            doc_data['gridColumns'] = val
                    except (ValueError, TypeError):
                        pass

            # collections uniquement pour le type "guide_collections"
            if section_type == 'guide_collections':
                raw_collections = section.get('collections', [])
                if not isinstance(raw_collections, list):
                    raw_collections = []
                collections = []
                for idx, col in enumerate(raw_collections):
                    if not isinstance(col, dict):
                        continue
                    title_col = (col.get('title') or '').strip()
                    if not title_col:
                        continue
                    image_id = (col.get('imageId') or '').strip()
                    image_url = (col.get('imageUrl') or '').strip()
                    raw_guide_ids = col.get('guideIds', [])
                    if not isinstance(raw_guide_ids, list):
                        raw_guide_ids = []
                    guide_ids = [g for g in raw_guide_ids if isinstance(g, str) and g.strip()]
                    collections.append({
                        'id': (col.get('id') or '').strip() or f"col_{int(datetime.utcnow().timestamp() * 1000)}_{idx}",
                        'title': title_col,
                        'subtitle': (col.get('subtitle') or '').strip(),
                        'imageId': image_id,
                        'imageUrl': image_url,
                        'guideIds': guide_ids,
                        'order': int(col.get('order', idx) or idx),
                    })
                collections.sort(key=lambda c: c['order'])
                doc_data['collections'] = collections

            # buttons uniquement pour le type "decide"
            if section_type == 'decide':
                VALID_BUTTON_IDS = ('swipe', 'spinner', 'battle')
                raw_buttons = section.get('buttons', [])
                if not isinstance(raw_buttons, list):
                    raw_buttons = []
                buttons = []
                for btn in raw_buttons:
                    if not isinstance(btn, dict):
                        continue
                    btn_id = (btn.get('id') or '').strip()
                    if btn_id not in VALID_BUTTON_IDS:
                        continue
                    buttons.append({
                        'id': btn_id,
                        'label': (btn.get('label') or btn_id).strip(),
                        'enabled': bool(btn.get('enabled', True)),
                        'order': int(btn.get('order', 0) or 0),
                    })
                buttons.sort(key=lambda b: b['order'])
                doc_data['buttons'] = buttons

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


@login_required
def home_sections_order(request):
    """Page dédiée au réordonnancement des sections de la home."""
    try:
        db = get_firestore_client(request)

        sections_docs = db.collection(COLLECTION).get()
        sections = []
        for doc in sections_docs:
            data = doc.to_dict()
            data['id'] = doc.id
            sections.append(data)

        sections.sort(key=lambda s: (s.get('city', ''), s.get('order', 999)))

        # Villes présentes
        cities = sorted(set(s.get('city', 'Paris') for s in sections))

        context = {
            'sections': sections,
            'sections_json': json.dumps(sections, default=str),
            'cities': cities,
            'cities_json': json.dumps(cities),
        }
        return render(request, 'scripts_manager/home_sections/order.html', context)

    except Exception as e:
        logger.exception("Erreur home_sections_order: %s", e)
        messages.error(request, f"Erreur : {str(e)}")
        return render(request, 'scripts_manager/home_sections/order.html', {
            'sections': [], 'sections_json': '[]',
            'cities': [], 'cities_json': '[]',
        })


@require_http_methods(["POST"])
@login_required
def home_sections_order_save(request):
    """Sauvegarde l'ordre des sections (uniquement les orders)."""
    try:
        db = get_firestore_client(request)
        raw = request.POST.get('order_data', '[]')
        order_data = json.loads(raw)

        if not isinstance(order_data, list):
            messages.error(request, "Données invalides")
            return redirect('scripts_manager:home_sections_order')

        updated = 0
        for item in order_data:
            section_id = item.get('id', '').strip()
            order = int(item.get('order', 0))
            if section_id:
                db.collection(COLLECTION).document(section_id).update({
                    'order': order,
                    'updatedAt': datetime.utcnow(),
                })
                updated += 1

        messages.success(request, f"Ordre mis à jour ({updated} sections)")

    except json.JSONDecodeError:
        messages.error(request, "Erreur de format JSON")
    except Exception as e:
        logger.exception("Erreur home_sections_order_save: %s", e)
        messages.error(request, f"Erreur : {str(e)}")

    return redirect('scripts_manager:home_sections_order')


CITIES = ['Paris', 'Marrakech']


@require_http_methods(["POST"])
@login_required
def home_sections_seed_types(request):
    """Seed les sections videos pour chaque ville active + tag les anciennes en 'guides'."""
    try:
        db = get_firestore_client(request)

        docs = list(db.collection(COLLECTION).get())
        sections = []
        for doc in docs:
            data = doc.to_dict()
            data['_id'] = doc.id
            sections.append(data)

        migrated = 0
        created = 0

        # 1. Ajouter type="guides" aux sections existantes sans type
        for s in sections:
            if not s.get('type'):
                db.collection(COLLECTION).document(s['_id']).update({
                    'type': 'guides',
                    'updatedAt': datetime.utcnow(),
                })
                s['type'] = 'guides'
                migrated += 1

        # 2. Créer videos pour chaque ville si absent
        for city in CITIES:
            city_sections = [s for s in sections if s.get('city') == city]
            city_types = {s.get('type') for s in city_sections}
            existing_orders = [s.get('order', 0) for s in city_sections]
            max_order = max(existing_orders) if existing_orders else -1

            if 'videos' not in city_types:
                db.collection(COLLECTION).add({
                    'title': 'Nos dégustations',
                    'type': 'videos',
                    'order': max_order + 1,
                    'isActive': True,
                    'city': city,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                })
                created += 1

        msg_parts = []
        if migrated:
            msg_parts.append(f"{migrated} section(s) migrée(s) avec type='guides'")
        if created:
            msg_parts.append(f"{created} section(s) créée(s)")
        if msg_parts:
            messages.success(request, ' · '.join(msg_parts))
        else:
            messages.info(request, "Toutes les sections ont déjà un type — rien à faire")

    except Exception as e:
        logger.exception("Erreur home_sections_seed_types: %s", e)
        messages.error(request, f"Erreur : {str(e)}")

    return redirect('scripts_manager:home_sections_manage')
