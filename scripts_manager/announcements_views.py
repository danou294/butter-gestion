"""
Views pour la gestion des Annonces (Événements et Sondages) dans le backoffice Django
Écrit directement dans Firestore (collection 'announcements')
Compatible dev/prod via get_firestore_client(request).
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from datetime import datetime
import json
import csv
import os

from google.cloud import firestore
from .restaurants_views import get_firestore_client
from .config import FIREBASE_BUCKET_PROD

PHOTOS_PREFIX = "Photos restaurants/"
ANNOUNCEMENTS_STORAGE_PREFIX = "Annonces/"


def _build_image_url(bucket, image_ref):
    """Construit l'URL publique d'une image depuis le bucket et la ref (ex: CHEJ3)."""
    if not bucket or not image_ref:
        return None
    path_encoded = "Photos%20restaurants%2F" + image_ref.strip() + ".webp"
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{path_encoded}?alt=media"


def _get_next_announcement_id(db, announcement_type):
    """
    Lit et incrémente le compteur Firestore (_meta/announcements_counters),
    retourne le prochain ID : EVENT001, POLL001, etc.
    """
    counter_ref = db.collection('_meta').document('announcements_counters')
    transaction = db.transaction()

    @firestore.transactional
    def _increment(transaction, counter_ref, announcement_type):
        result = transaction.get(counter_ref)
        # transaction.get() renvoie un générateur ou une liste, pas un snapshot unique
        if hasattr(result, 'to_dict'):
            snapshot = result
        else:
            snapshot = next(iter(result))
        data = snapshot.to_dict() or {}
        if announcement_type == 'event':
            seq = (data.get('eventSeq') or 0) + 1
            new_data = {**data, 'eventSeq': seq, 'updatedAt': datetime.utcnow()}
            transaction.set(counter_ref, new_data, merge=True)
            return f"EVENT{str(seq).zfill(3)}"
        else:
            seq = (data.get('pollSeq') or 0) + 1
            new_data = {**data, 'pollSeq': seq, 'updatedAt': datetime.utcnow()}
            transaction.set(counter_ref, new_data, merge=True)
            return f"POLL{str(seq).zfill(3)}"

    return _increment(transaction, counter_ref, announcement_type)


def _date_for_input(value):
    """Convertit une date Firestore/datetime en chaîne YYYY-MM-DD pour input type=date."""
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    if hasattr(value, 'date'):
        return value.date().strftime('%Y-%m-%d')
    return str(value)[:10] if value else ''


# ==================== LISTE DES ANNONCES ====================

@login_required
def announcements_list(request):
    """
    Affiche la liste de toutes les annonces (événements + sondages)
    """
    try:
        db = get_firestore_client(request)
        announcements_ref = db.collection('announcements')

        announcements_docs = announcements_ref.order_by('createdAt', direction='DESCENDING').stream()

        announcements = []
        events_count = 0
        polls_count = 0
        premium_count = 0
        active_count = 0

        for doc in announcements_docs:
            data = doc.to_dict()
            data['id'] = doc.id
            announcements.append(data)

            if data.get('type') == 'event':
                events_count += 1
            elif data.get('type') == 'poll':
                polls_count += 1

            if data.get('isPremium', False):
                premium_count += 1

            if data.get('isActive', False):
                active_count += 1

        context = {
            'announcements': announcements,
            'total_count': len(announcements),
            'events_count': events_count,
            'polls_count': polls_count,
            'premium_count': premium_count,
            'active_count': active_count,
        }

        return render(request, 'scripts_manager/announcements/list.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement des annonces : {str(e)}")
        return render(request, 'scripts_manager/announcements/list.html', {
            'announcements': [],
            'total_count': 0,
            'events_count': 0,
            'polls_count': 0,
            'premium_count': 0,
            'active_count': 0,
        })


# ==================== DÉTAIL D'UNE ANNONCE ====================

@login_required
def announcement_detail(request, announcement_id):
    """
    Affiche le détail d'une annonce avec statistiques
    """
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection('announcements').document(announcement_id)
        doc = doc_ref.get()

        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('scripts_manager:announcements_list')

        announcement_data = doc.to_dict()
        announcement_data['id'] = doc.id

        poll_stats = None
        if announcement_data.get('type') == 'poll':
            poll_stats = _get_poll_statistics(db, announcement_id)

        event_stats = None
        if announcement_data.get('type') == 'event':
            event_stats = _get_event_statistics(db, announcement_id)

        context = {
            'announcement': announcement_data,
            'poll_stats': poll_stats,
            'event_stats': event_stats,
        }

        return render(request, 'scripts_manager/announcements/detail.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement de l'annonce : {str(e)}")
        return redirect('scripts_manager:announcements_list')


def _get_poll_statistics(db, poll_id):
    """Récupère les statistiques d'un sondage"""
    try:
        answers_ref = db.collection('poll_answers').where('pollId', '==', poll_id)
        answers_docs = answers_ref.stream()

        answers = []
        answer_counts = {}
        total_votes = 0

        for doc in answers_docs:
            data = doc.to_dict()
            answer = (data.get('answer') or '').strip().lower()
            answers.append(data)
            total_votes += 1
            if answer:
                answer_counts[answer] = answer_counts.get(answer, 0) + 1

        sorted_answers = sorted(answer_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            'total_votes': total_votes,
            'unique_answers': len(answer_counts),
            'top_answers': sorted_answers[:10],
            'all_answers': answers,
        }
    except Exception as e:
        return None


def _get_event_statistics(db, event_id):
    """Récupère les statistiques d'un événement"""
    try:
        clicks_ref = db.collection('event_clicks').where('eventId', '==', event_id)
        clicks_docs = clicks_ref.stream()

        total_clicks = 0
        unique_users = set()

        for doc in clicks_docs:
            data = doc.to_dict()
            total_clicks += 1
            uid = data.get('userId')
            if uid:
                unique_users.add(uid)

        return {
            'total_clicks': total_clicks,
            'unique_users': len(unique_users),
        }
    except Exception as e:
        return None


# ==================== CRÉER UNE ANNONCE ====================

@login_required
def announcement_create(request):
    """
    Formulaire de création d'une annonce
    """
    if request.method == 'POST':
        try:
            db = get_firestore_client(request)

            announcement_type = request.POST.get('type', 'event').strip()
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            image_url = request.POST.get('imageUrl', '').strip()
            image_ref = request.POST.get('imageRef', '').strip()
            is_premium = request.POST.get('isPremium') == 'on'
            is_active = request.POST.get('isActive') == 'on'

            start_date_str = request.POST.get('startDate', '').strip()
            end_date_str = request.POST.get('endDate', '').strip()

            if not title:
                messages.error(request, "Le titre est requis")
                return render(request, 'scripts_manager/announcements/form.html', {
                    'form_data': request.POST,
                    'mode': 'create',
                    'firebase_bucket': FIREBASE_BUCKET_PROD,
                })

            # ID auto-incrémenté (EVENT001, POLL001, ...)
            announcement_id = _get_next_announcement_id(db, announcement_type)

            # Image : priorité à la ref Storage (depuis le sélecteur) puis URL manuelle
            if image_ref:
                bucket = FIREBASE_BUCKET_PROD
                image_url = _build_image_url(bucket, image_ref) or image_url
            if not image_url:
                image_url = None

            doc_ref = db.collection('announcements').document(announcement_id)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None

            announcement_data = {
                'id': announcement_id,
                'type': announcement_type,
                'title': title,
                'description': description,
                'imageUrl': image_url,
                'isPremium': is_premium,
                'isActive': is_active,
                'startDate': start_date,
                'endDate': end_date,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
            }

            if announcement_type == 'event':
                cta_text = request.POST.get('ctaText', '').strip()
                cta_link = request.POST.get('ctaLink', '').strip()
                event_date_str = request.POST.get('eventDate', '').strip()
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else None
                announcement_data.update({
                    'ctaText': cta_text if cta_text else 'En savoir plus',
                    'ctaLink': cta_link,
                    'eventDate': event_date,
                })
            elif announcement_type == 'poll':
                poll_question = request.POST.get('pollQuestion', '').strip()
                announcement_data.update({
                    'pollQuestion': poll_question if poll_question else title,
                })

            doc_ref.set(announcement_data)

            type_label = "Événement" if announcement_type == 'event' else "Sondage"
            messages.success(request, f"{type_label} '{title}' créé avec succès !")
            return redirect('scripts_manager:announcement_detail', announcement_id=announcement_id)

        except ValueError as e:
            messages.error(request, f"Erreur de validation : {str(e)}")
            return render(request, 'scripts_manager/announcements/form.html', {
                'form_data': request.POST,
                'mode': 'create',
                'firebase_bucket': FIREBASE_BUCKET_PROD,
            })
        except Exception as e:
            messages.error(request, f"Erreur lors de la création : {str(e)}")
            return render(request, 'scripts_manager/announcements/form.html', {
                'form_data': request.POST,
                'mode': 'create',
                'firebase_bucket': FIREBASE_BUCKET_PROD,
            })

    return render(request, 'scripts_manager/announcements/form.html', {
        'mode': 'create',
        'firebase_bucket': FIREBASE_BUCKET_PROD,
    })


# ==================== ÉDITER UNE ANNONCE ====================

@login_required
def announcement_edit(request, announcement_id):
    """
    Formulaire d'édition d'une annonce
    """
    db = get_firestore_client(request)
    doc_ref = db.collection('announcements').document(announcement_id)

    if request.method == 'POST':
        try:
            doc = doc_ref.get()
            if not doc.exists:
                messages.error(request, f"Annonce '{announcement_id}' non trouvée")
                return redirect('scripts_manager:announcements_list')

            announcement_type = request.POST.get('type', 'event').strip()
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            image_url = request.POST.get('imageUrl', '').strip()
            image_ref = request.POST.get('imageRef', '').strip()

            if image_ref:
                bucket = FIREBASE_BUCKET_PROD
                image_url = _build_image_url(bucket, image_ref) or image_url
            if not image_url:
                image_url = None

            is_premium = request.POST.get('isPremium') == 'on'
            is_active = request.POST.get('isActive') == 'on'

            start_date_str = request.POST.get('startDate', '').strip()
            end_date_str = request.POST.get('endDate', '').strip()

            if not title:
                messages.error(request, "Le titre est requis")
                return redirect('scripts_manager:announcement_edit', announcement_id=announcement_id)

            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None

            update_data = {
                'type': announcement_type,
                'title': title,
                'description': description,
                'imageUrl': image_url,
                'isPremium': is_premium,
                'isActive': is_active,
                'startDate': start_date,
                'endDate': end_date,
                'updatedAt': datetime.utcnow(),
            }

            if announcement_type == 'event':
                cta_text = request.POST.get('ctaText', '').strip()
                cta_link = request.POST.get('ctaLink', '').strip()
                event_date_str = request.POST.get('eventDate', '').strip()
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else None
                update_data.update({
                    'ctaText': cta_text,
                    'ctaLink': cta_link,
                    'eventDate': event_date,
                })
            elif announcement_type == 'poll':
                poll_question = request.POST.get('pollQuestion', '').strip()
                update_data.update({
                    'pollQuestion': poll_question,
                })

            doc_ref.update(update_data)

            type_label = "Événement" if announcement_type == 'event' else "Sondage"
            messages.success(request, f"{type_label} '{title}' mis à jour avec succès !")
            return redirect('scripts_manager:announcement_detail', announcement_id=announcement_id)

        except Exception as e:
            messages.error(request, f"Erreur lors de la mise à jour : {str(e)}")
            return redirect('scripts_manager:announcement_edit', announcement_id=announcement_id)

    # GET
    try:
        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('scripts_manager:announcements_list')

        announcement_data = doc.to_dict()
        announcement_data['id'] = announcement_id

        announcement_data['startDate_formatted'] = _date_for_input(announcement_data.get('startDate'))
        announcement_data['endDate_formatted'] = _date_for_input(announcement_data.get('endDate'))
        announcement_data['eventDate_formatted'] = _date_for_input(announcement_data.get('eventDate'))

        context = {
            'announcement': announcement_data,
            'announcement_id': announcement_id,
            'mode': 'edit',
            'firebase_bucket': FIREBASE_BUCKET_PROD,
        }

        return render(request, 'scripts_manager/announcements/form.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement : {str(e)}")
        return redirect('scripts_manager:announcements_list')


# ==================== UPLOAD IMAGE ANNONCE (DEPUIS L'ORDINATEUR) ====================

def _get_storage_client_prod():
    """Client Storage PROD uniquement (pas de doublon photos dev/prod)."""
    from google.cloud import storage
    from google.oauth2 import service_account
    from .config import FIREBASE_CREDENTIALS_DIR
    path = str(FIREBASE_CREDENTIALS_DIR / "serviceAccountKey.prod.json")
    if not os.path.exists(path):
        return None
    creds = service_account.Credentials.from_service_account_file(
        path,
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    return storage.Client(credentials=creds, project=creds.project_id)


@require_http_methods(["POST"])
@login_required
def announcement_upload_image(request):
    """
    Upload une image depuis l'ordinateur vers le bucket PROD uniquement (dossier Annonces/).
    Le bucket Storage est toujours PROD pour ne pas dupliquer les photos.
    """
    if 'image_file' not in request.FILES:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    upload_file = request.FILES['image_file']
    allowed_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
    ext = os.path.splitext(upload_file.name or '')[1].lower()
    if ext not in allowed_extensions:
        return JsonResponse({
            'error': f'Format non supporté. Utilisez : {", ".join(allowed_extensions)}'
        }, status=400)

    try:
        client = _get_storage_client_prod()
        if not client:
            return JsonResponse({'error': 'Storage PROD indisponible'}, status=503)

        base_name = os.path.splitext((upload_file.name or 'image').replace(' ', '_'))[0]
        safe_base = "".join(c for c in base_name if c.isalnum() or c in '-_')[:50] or 'image'
        unique_name = f"{safe_base}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
        full_path = f"{ANNOUNCEMENTS_STORAGE_PREFIX}{unique_name}"

        bucket = client.bucket(FIREBASE_BUCKET_PROD)
        blob = bucket.blob(full_path)

        content_type = upload_file.content_type or (
            'image/webp' if ext == '.webp' else
            'image/png' if ext == '.png' else 'image/jpeg'
        )
        upload_file.seek(0)
        blob.upload_from_file(upload_file, content_type=content_type)

        url = _build_image_url_announcement(FIREBASE_BUCKET_PROD, full_path)
        return JsonResponse({
            'url': url,
            'filename': unique_name,
            'path': full_path,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def _build_image_url_announcement(bucket, storage_path):
    """Construit l'URL publique d'une image dans le dossier Annonces/."""
    if not bucket or not storage_path:
        return None
    from urllib.parse import quote
    encoded = quote(storage_path, safe='')
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{encoded}?alt=media"


# ==================== LISTE IMAGES STORAGE (PAR ID RESTAURANT) ====================

@login_required
def list_storage_images(request):
    """
    API JSON : liste les images du Storage PROD pour un restaurant donné.
    Le bucket est toujours PROD (pas de photos en dev).
    GET ?restaurant_id=CHEJ → { "images": ["CHEJ1", "CHEJ2"], "bucket": "..." }
    """
    restaurant_id = (request.GET.get('restaurant_id') or '').strip().upper()
    if not restaurant_id:
        return JsonResponse({'error': 'restaurant_id requis', 'images': [], 'bucket': ''}, status=400)

    try:
        client = _get_storage_client_prod()
        if not client:
            return JsonResponse({'error': 'Storage PROD indisponible', 'images': [], 'bucket': ''}, status=503)
        bucket = client.bucket(FIREBASE_BUCKET_PROD)
        prefix = f"{PHOTOS_PREFIX}{restaurant_id}"
        blobs = list(bucket.list_blobs(prefix=prefix))

        images = []
        for blob in blobs:
            name = blob.name.replace(PHOTOS_PREFIX, '')
            if name.lower().endswith('.webp'):
                ref = name[:-5]  # sans .webp
                if ref:
                    images.append(ref)
        images.sort(key=lambda x: (len(x), x))

        return JsonResponse({
            'images': images,
            'bucket': FIREBASE_BUCKET_PROD,
        })
    except Exception as e:
        return JsonResponse({'error': str(e), 'images': [], 'bucket': ''}, status=500)


# ==================== SUPPRIMER UNE ANNONCE ====================

@login_required
@require_http_methods(["POST"])
def announcement_delete(request, announcement_id):
    """
    Supprime une annonce de Firestore
    """
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection('announcements').document(announcement_id)

        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('scripts_manager:announcements_list')

        announcement_title = doc.to_dict().get('title', announcement_id)
        doc_ref.delete()

        messages.success(request, f"Annonce '{announcement_title}' supprimée avec succès")
        return redirect('scripts_manager:announcements_list')

    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
        return redirect('scripts_manager:announcements_list')


# ==================== EXPORT RÉPONSES SONDAGE ====================

@login_required
def poll_export_answers(request, announcement_id):
    """
    Exporte les réponses d'un sondage en CSV
    """
    try:
        db = get_firestore_client(request)

        poll_doc = db.collection('announcements').document(announcement_id).get()
        if not poll_doc.exists:
            messages.error(request, f"Sondage '{announcement_id}' non trouvé")
            return redirect('scripts_manager:announcements_list')

        answers_ref = db.collection('poll_answers').where('pollId', '==', announcement_id)
        answers_docs = answers_ref.stream()

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="poll_{announcement_id}_answers.csv"'
        response.write('\ufeff')

        writer = csv.writer(response, delimiter=';')
        writer.writerow(['User ID', 'Réponse', 'Date'])

        for doc in answers_docs:
            data = doc.to_dict()
            user_id = data.get('userId', '')
            answer = data.get('answer', '')
            submitted_at = data.get('submittedAt')
            date_str = submitted_at.strftime('%Y-%m-%d %H:%M:%S') if submitted_at and hasattr(submitted_at, 'strftime') else ''
            writer.writerow([user_id, answer, date_str])

        return response

    except Exception as e:
        messages.error(request, f"Erreur lors de l'export : {str(e)}")
        return redirect('scripts_manager:announcement_detail', announcement_id=announcement_id)


# ==================== EXPORT JSON ====================

@login_required
def announcement_get_json(request, announcement_id):
    """
    Retourne le JSON d'une annonce
    """
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection('announcements').document(announcement_id)
        doc = doc_ref.get()

        if not doc.exists:
            return JsonResponse({'error': 'Annonce non trouvée'}, status=404)

        announcement_data = doc.to_dict()
        announcement_data['id'] = doc.id

        for key in ['createdAt', 'updatedAt', 'startDate', 'endDate', 'eventDate']:
            if key in announcement_data and announcement_data[key]:
                val = announcement_data[key]
                announcement_data[key] = val.isoformat() if hasattr(val, 'isoformat') else str(val)

        return JsonResponse(announcement_data, json_dumps_params={'indent': 2})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
