"""
Views pour la gestion des Vidéos (Butter Reels) dans le backoffice Django.
Upload vers Firebase Storage (Videos/), métadonnées dans Firestore (collection 'videos').
Compatible dev/prod via get_firestore_client(request).
Storage toujours PROD (comme les photos).
"""

import os
import json
import logging
from datetime import datetime
from urllib.parse import quote

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from google.cloud import firestore

from .restaurants_views import get_firestore_client
from .photos_views import get_storage_client, get_storage_credentials
from .firebase_utils import get_firebase_bucket, get_firebase_env_from_session
from .config import FIREBASE_BUCKET_PROD

logger = logging.getLogger(__name__)

VIDEOS_STORAGE_PREFIX = "Videos/"
VIDEOS_COLLECTION = "videos"
VIDEOS_PAGE_SIZE = 20

# Extensions vidéo autorisées
ALLOWED_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.m4v')
ALLOWED_THUMB_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')

# Limite de taille : 100 MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024


def _build_storage_url(bucket, storage_path):
    """Construit l'URL publique Firebase Storage depuis le bucket et le path."""
    if not bucket or not storage_path:
        return None
    encoded = quote(storage_path, safe='')
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{encoded}?alt=media"


def _get_next_video_id(db):
    """
    Lit et incrémente le compteur Firestore (_meta/videos_counters).
    Retourne le prochain ID : VID001, VID002, etc.
    """
    counter_ref = db.collection('_meta').document('videos_counters')
    transaction = db.transaction()

    @firestore.transactional
    def _increment(transaction, counter_ref):
        result = transaction.get(counter_ref)
        if hasattr(result, 'to_dict'):
            snapshot = result
        else:
            snapshots = list(result)
            if not snapshots:
                # Premier appel : créer le compteur
                transaction.set(counter_ref, {'videoSeq': 1, 'createdAt': datetime.utcnow()})
                return "VID001"
            snapshot = snapshots[0]
        data = snapshot.to_dict() or {}
        seq = (data.get('videoSeq') or 0) + 1
        transaction.set(counter_ref, {**data, 'videoSeq': seq, 'updatedAt': datetime.utcnow()}, merge=True)
        return f"VID{str(seq).zfill(3)}"

    return _increment(transaction, counter_ref)


# ==================== LISTE DES VIDÉOS ====================

@login_required
def videos_list(request):
    """Liste toutes les vidéos avec stats."""
    try:
        db = get_firestore_client(request)
        docs = db.collection(VIDEOS_COLLECTION).get()

        videos = []
        active_count = 0
        cities = set()

        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            videos.append(data)
            if data.get('isActive', False):
                active_count += 1
            city = data.get('city', '')
            if city:
                cities.add(city)

        # Tri par order puis createdAt desc
        videos.sort(key=lambda x: (x.get('order', 999), -(x.get('createdAt', datetime.min).timestamp() if hasattr(x.get('createdAt', datetime.min), 'timestamp') else 0)))

        # Filtres
        filter_city = request.GET.get('city', '').strip()
        filter_active = request.GET.get('active', '').strip()

        if filter_city:
            videos = [v for v in videos if v.get('city', '').lower() == filter_city.lower()]
        if filter_active == '1':
            videos = [v for v in videos if v.get('isActive', False)]
        elif filter_active == '0':
            videos = [v for v in videos if not v.get('isActive', False)]

        context = {
            'videos': videos,
            'total_count': len(videos),
            'active_count': active_count,
            'cities': sorted(cities),
            'filter_city': filter_city,
            'filter_active': filter_active,
        }
        return render(request, 'scripts_manager/videos/list.html', context)

    except Exception as e:
        logger.exception("Erreur videos_list: %s", e)
        messages.error(request, f"Erreur lors du chargement des vidéos : {str(e)}")
        return render(request, 'scripts_manager/videos/list.html', {
            'videos': [], 'total_count': 0, 'active_count': 0,
            'cities': [], 'filter_city': '', 'filter_active': '',
        })


# ==================== UPLOAD VIDÉO ====================

@login_required
def video_upload(request):
    """Formulaire d'upload d'une nouvelle vidéo."""
    if request.method == 'POST':
        try:
            db = get_firestore_client(request)

            # Champs du formulaire
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            city = request.POST.get('city', 'paris').strip().lower()
            restaurant_id = request.POST.get('restaurantId', '').strip()
            is_active = request.POST.get('isActive') == 'on'
            order = int(request.POST.get('order', 0) or 0)

            if not title:
                messages.error(request, "Le titre est requis")
                return render(request, 'scripts_manager/videos/upload.html', {
                    'form_data': request.POST, 'mode': 'create',
                })

            # Fichier vidéo
            if 'video_file' not in request.FILES:
                messages.error(request, "Le fichier vidéo est requis")
                return render(request, 'scripts_manager/videos/upload.html', {
                    'form_data': request.POST, 'mode': 'create',
                })

            video_file = request.FILES['video_file']
            ext = os.path.splitext(video_file.name or '')[1].lower()

            if ext not in ALLOWED_VIDEO_EXTENSIONS:
                messages.error(request, f"Format non supporté. Utilisez : {', '.join(ALLOWED_VIDEO_EXTENSIONS)}")
                return render(request, 'scripts_manager/videos/upload.html', {
                    'form_data': request.POST, 'mode': 'create',
                })

            if video_file.size > MAX_VIDEO_SIZE:
                messages.error(request, f"Fichier trop lourd ({video_file.size // (1024*1024)} MB). Max : {MAX_VIDEO_SIZE // (1024*1024)} MB")
                return render(request, 'scripts_manager/videos/upload.html', {
                    'form_data': request.POST, 'mode': 'create',
                })

            # Générer l'ID
            video_id = _get_next_video_id(db)

            # Upload vidéo vers Storage
            client = get_storage_client(request)
            if not client:
                messages.error(request, "Erreur de connexion à Firebase Storage")
                return render(request, 'scripts_manager/videos/upload.html', {
                    'form_data': request.POST, 'mode': 'create',
                })

            bucket = client.bucket(get_firebase_bucket(request))

            video_storage_path = f"{VIDEOS_STORAGE_PREFIX}{video_id}{ext}"
            blob = bucket.blob(video_storage_path)
            content_type = 'video/mp4' if ext == '.mp4' else 'video/quicktime'
            video_file.seek(0)
            blob.upload_from_file(video_file, content_type=content_type)
            video_url = _build_storage_url(FIREBASE_BUCKET_PROD, video_storage_path)

            logger.info(f"Video uploaded: {video_storage_path} ({video_file.size // 1024} KB)")

            # Upload thumbnail (optionnel)
            thumbnail_url = None
            if 'thumbnail_file' in request.FILES:
                thumb_file = request.FILES['thumbnail_file']
                thumb_ext = os.path.splitext(thumb_file.name or '')[1].lower()
                if thumb_ext in ALLOWED_THUMB_EXTENSIONS:
                    thumb_storage_path = f"{VIDEOS_STORAGE_PREFIX}{video_id}_thumb{thumb_ext}"
                    thumb_blob = bucket.blob(thumb_storage_path)
                    thumb_content_type = thumb_file.content_type or 'image/jpeg'
                    thumb_file.seek(0)
                    thumb_blob.upload_from_file(thumb_file, content_type=thumb_content_type)
                    thumbnail_url = _build_storage_url(FIREBASE_BUCKET_PROD, thumb_storage_path)
                    logger.info(f"Thumbnail uploaded: {thumb_storage_path}")

            # Vérifier que le restaurant existe (si fourni)
            restaurant_name = None
            if restaurant_id:
                rest_doc = db.collection('restaurants').document(restaurant_id).get()
                if rest_doc.exists:
                    restaurant_name = rest_doc.to_dict().get('vraiNom', rest_doc.to_dict().get('name', restaurant_id))
                else:
                    logger.warning(f"Restaurant '{restaurant_id}' non trouvé, lien ignoré")
                    restaurant_id = ''

            # Créer le document Firestore
            video_data = {
                'id': video_id,
                'title': title,
                'description': description,
                'city': city,
                'restaurantId': restaurant_id if restaurant_id else None,
                'restaurantName': restaurant_name,
                'videoUrl': video_url,
                'thumbnailUrl': thumbnail_url,
                'storagePath': video_storage_path,
                'likesCount': 0,
                'commentsCount': 0,
                'viewsCount': 0,
                'duration': None,  # sera set côté Flutter ou manuellement
                'isActive': is_active,
                'order': order,
                'uploadedBy': request.user.username if request.user.is_authenticated else 'admin',
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
            }

            db.collection(VIDEOS_COLLECTION).document(video_id).set(video_data)

            messages.success(request, f"Vidéo '{title}' ({video_id}) uploadée avec succès !")
            return redirect('scripts_manager:video_detail', video_id=video_id)

        except Exception as e:
            logger.exception("Erreur video_upload: %s", e)
            messages.error(request, f"Erreur lors de l'upload : {str(e)}")
            return render(request, 'scripts_manager/videos/upload.html', {
                'form_data': request.POST, 'mode': 'create',
            })

    # GET — charger les restaurants pour le select searchable
    all_restaurants = []
    try:
        db = get_firestore_client(request)
        for rdoc in db.collection('restaurants').order_by('name').stream():
            rdata = rdoc.to_dict()
            all_restaurants.append({
                'id': rdoc.id,
                'name': rdata.get('name', rdoc.id),
                'cuisine': rdata.get('cuisine', ''),
                'city': rdata.get('city', 'Paris'),
            })
    except Exception:
        pass
    return render(request, 'scripts_manager/videos/upload.html', {
        'mode': 'create',
        'all_restaurants_json': json.dumps(all_restaurants, default=str),
    })


# ==================== UPLOAD MULTIPLE ====================

@login_required
def video_bulk_upload(request):
    """Page d'upload multiple de vidéos."""
    return render(request, 'scripts_manager/videos/bulk_upload.html')


@require_http_methods(["POST"])
@login_required
def video_bulk_upload_api(request):
    """API JSON pour uploader une seule vidéo (appelé N fois par le front bulk)."""
    try:
        db = get_firestore_client(request)

        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        city = request.POST.get('city', 'paris').strip().lower()
        restaurant_id = request.POST.get('restaurantId', '').strip()
        is_active = request.POST.get('isActive') == 'on'
        order = int(request.POST.get('order', 0) or 0)

        if not title:
            return JsonResponse({'success': False, 'error': 'Le titre est requis'}, status=400)

        if 'video_file' not in request.FILES:
            return JsonResponse({'success': False, 'error': 'Fichier vidéo requis'}, status=400)

        video_file = request.FILES['video_file']
        ext = os.path.splitext(video_file.name or '')[1].lower()

        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            return JsonResponse({'success': False, 'error': f'Format non supporté ({ext})'}, status=400)

        if video_file.size > MAX_VIDEO_SIZE:
            return JsonResponse({'success': False, 'error': f'Trop lourd ({video_file.size // (1024*1024)} MB)'}, status=400)

        # Générer l'ID
        video_id = _get_next_video_id(db)

        # Upload vers Storage
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'success': False, 'error': 'Erreur connexion Storage'}, status=500)

        bucket = client.bucket(get_firebase_bucket(request))

        video_storage_path = f"{VIDEOS_STORAGE_PREFIX}{video_id}{ext}"
        blob = bucket.blob(video_storage_path)
        content_type = 'video/mp4' if ext == '.mp4' else 'video/quicktime'
        video_file.seek(0)
        blob.upload_from_file(video_file, content_type=content_type)
        video_url = _build_storage_url(FIREBASE_BUCKET_PROD, video_storage_path)

        logger.info(f"[bulk] Video uploaded: {video_storage_path} ({video_file.size // 1024} KB)")

        # Vérifier restaurant
        restaurant_name = None
        if restaurant_id:
            rest_doc = db.collection('restaurants').document(restaurant_id).get()
            if rest_doc.exists:
                restaurant_name = rest_doc.to_dict().get('vraiNom', rest_doc.to_dict().get('name', restaurant_id))
            else:
                restaurant_id = ''

        # Créer doc Firestore
        video_data = {
            'id': video_id,
            'title': title,
            'description': description,
            'city': city,
            'restaurantId': restaurant_id if restaurant_id else None,
            'restaurantName': restaurant_name,
            'videoUrl': video_url,
            'thumbnailUrl': None,
            'storagePath': video_storage_path,
            'likesCount': 0,
            'commentsCount': 0,
            'viewsCount': 0,
            'duration': None,
            'isActive': is_active,
            'order': order,
            'uploadedBy': request.user.username if request.user.is_authenticated else 'admin',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }

        db.collection(VIDEOS_COLLECTION).document(video_id).set(video_data)

        return JsonResponse({
            'success': True,
            'video_id': video_id,
            'title': title,
            'message': f'Vidéo {video_id} uploadée',
        })

    except Exception as e:
        logger.exception("[bulk] Erreur video_bulk_upload_api: %s", e)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== DÉTAIL VIDÉO ====================

@login_required
def video_detail(request, video_id):
    """Affiche le détail d'une vidéo avec commentaires et stats."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(VIDEOS_COLLECTION).document(video_id).get()

        if not doc.exists:
            messages.error(request, f"Vidéo '{video_id}' non trouvée")
            return redirect('scripts_manager:videos_list')

        video = doc.to_dict()
        video['id'] = doc.id

        # Charger les commentaires
        comments = []
        comments_docs = db.collection(VIDEOS_COLLECTION).document(video_id).collection('comments').order_by('createdAt', direction=firestore.Query.DESCENDING).get()
        for cdoc in comments_docs:
            cdata = cdoc.to_dict()
            cdata['id'] = cdoc.id
            comments.append(cdata)

        # Charger les likes count (vérification)
        likes_docs = db.collection(VIDEOS_COLLECTION).document(video_id).collection('likes').get()
        actual_likes = len(list(likes_docs))

        context = {
            'video': video,
            'comments': comments,
            'comments_count': len(comments),
            'actual_likes': actual_likes,
        }
        return render(request, 'scripts_manager/videos/detail.html', context)

    except Exception as e:
        logger.exception("Erreur video_detail: %s", e)
        messages.error(request, f"Erreur : {str(e)}")
        return redirect('scripts_manager:videos_list')


# ==================== ÉDITER VIDÉO ====================

@login_required
def video_edit(request, video_id):
    """Édite les métadonnées d'une vidéo (pas le fichier)."""
    db = get_firestore_client(request)
    doc_ref = db.collection(VIDEOS_COLLECTION).document(video_id)

    if request.method == 'POST':
        try:
            doc = doc_ref.get()
            if not doc.exists:
                messages.error(request, f"Vidéo '{video_id}' non trouvée")
                return redirect('scripts_manager:videos_list')

            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            city = request.POST.get('city', 'paris').strip().lower()
            restaurant_id = request.POST.get('restaurantId', '').strip()
            is_active = request.POST.get('isActive') == 'on'
            order = int(request.POST.get('order', 0) or 0)

            if not title:
                messages.error(request, "Le titre est requis")
                return redirect('scripts_manager:video_edit', video_id=video_id)

            # Vérifier restaurant
            restaurant_name = None
            if restaurant_id:
                rest_doc = db.collection('restaurants').document(restaurant_id).get()
                if rest_doc.exists:
                    restaurant_name = rest_doc.to_dict().get('vraiNom', rest_doc.to_dict().get('name', restaurant_id))
                else:
                    restaurant_id = ''

            update_data = {
                'title': title,
                'description': description,
                'city': city,
                'restaurantId': restaurant_id if restaurant_id else None,
                'restaurantName': restaurant_name,
                'isActive': is_active,
                'order': order,
                'updatedAt': datetime.utcnow(),
            }

            # Upload nouvelle thumbnail si fournie
            if 'thumbnail_file' in request.FILES:
                thumb_file = request.FILES['thumbnail_file']
                thumb_ext = os.path.splitext(thumb_file.name or '')[1].lower()
                if thumb_ext in ALLOWED_THUMB_EXTENSIONS:
                    client = get_storage_client(request)
                    if client:
                        bucket = client.bucket(get_firebase_bucket(request))
                        thumb_storage_path = f"{VIDEOS_STORAGE_PREFIX}{video_id}_thumb{thumb_ext}"
                        thumb_blob = bucket.blob(thumb_storage_path)
                        thumb_file.seek(0)
                        thumb_blob.upload_from_file(thumb_file, content_type=thumb_file.content_type or 'image/jpeg')
                        update_data['thumbnailUrl'] = _build_storage_url(FIREBASE_BUCKET_PROD, thumb_storage_path)

            doc_ref.update(update_data)
            messages.success(request, f"Vidéo '{title}' mise à jour !")
            return redirect('scripts_manager:video_detail', video_id=video_id)

        except Exception as e:
            logger.exception("Erreur video_edit: %s", e)
            messages.error(request, f"Erreur : {str(e)}")
            return redirect('scripts_manager:video_edit', video_id=video_id)

    # GET
    try:
        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Vidéo '{video_id}' non trouvée")
            return redirect('scripts_manager:videos_list')

        video = doc.to_dict()
        video['id'] = doc.id

        # Charger les restaurants pour le select searchable
        all_restaurants = []
        try:
            for rdoc in db.collection('restaurants').order_by('name').stream():
                rdata = rdoc.to_dict()
                all_restaurants.append({
                    'id': rdoc.id,
                    'name': rdata.get('name', rdoc.id),
                    'cuisine': rdata.get('cuisine', ''),
                    'city': rdata.get('city', 'Paris'),
                })
        except Exception:
            pass

        return render(request, 'scripts_manager/videos/upload.html', {
            'video': video, 'mode': 'edit', 'video_id': video_id,
            'all_restaurants_json': json.dumps(all_restaurants, default=str),
        })

    except Exception as e:
        messages.error(request, f"Erreur : {str(e)}")
        return redirect('scripts_manager:videos_list')


# ==================== SUPPRIMER VIDÉO ====================

@login_required
@require_http_methods(["POST"])
def video_delete(request, video_id):
    """Supprime une vidéo (Firestore + Storage)."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection(VIDEOS_COLLECTION).document(video_id)
        doc = doc_ref.get()

        if not doc.exists:
            messages.error(request, f"Vidéo '{video_id}' non trouvée")
            return redirect('scripts_manager:videos_list')

        video_data = doc.to_dict()
        video_title = video_data.get('title', video_id)

        # Supprimer les sous-collections (comments, likes)
        for subcol_name in ['comments', 'likes']:
            subcol_docs = doc_ref.collection(subcol_name).get()
            for subdoc in subcol_docs:
                subdoc.reference.delete()

        # Supprimer les fichiers Storage
        client = get_storage_client(request)
        if client:
            bucket = client.bucket(get_firebase_bucket(request))
            storage_path = video_data.get('storagePath', '')
            if storage_path:
                blob = bucket.blob(storage_path)
                if blob.exists():
                    blob.delete()
                    logger.info(f"Storage deleted: {storage_path}")

            # Supprimer thumbnail
            blobs = list(bucket.list_blobs(prefix=f"{VIDEOS_STORAGE_PREFIX}{video_id}_thumb"))
            for b in blobs:
                b.delete()
                logger.info(f"Thumbnail deleted: {b.name}")

        # Supprimer le document Firestore
        doc_ref.delete()
        messages.success(request, f"Vidéo '{video_title}' supprimée avec succès")
        return redirect('scripts_manager:videos_list')

    except Exception as e:
        logger.exception("Erreur video_delete: %s", e)
        messages.error(request, f"Erreur : {str(e)}")
        return redirect('scripts_manager:videos_list')


# ==================== TOGGLE ACTIF ====================

@login_required
@require_http_methods(["POST"])
def video_toggle_active(request, video_id):
    """Active/désactive une vidéo (API JSON)."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection(VIDEOS_COLLECTION).document(video_id)
        doc = doc_ref.get()

        if not doc.exists:
            return JsonResponse({'error': 'Vidéo non trouvée'}, status=404)

        current = doc.to_dict().get('isActive', False)
        doc_ref.update({'isActive': not current, 'updatedAt': datetime.utcnow()})

        return JsonResponse({'success': True, 'isActive': not current})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== SUPPRIMER UN COMMENTAIRE (MODÉRATION) ====================

@login_required
@require_http_methods(["POST"])
def video_delete_comment(request, video_id, comment_id):
    """Supprime un commentaire (modération)."""
    try:
        db = get_firestore_client(request)
        doc_ref = db.collection(VIDEOS_COLLECTION).document(video_id)

        # Vérifier que la vidéo existe
        if not doc_ref.get().exists:
            return JsonResponse({'error': 'Vidéo non trouvée'}, status=404)

        # Supprimer le commentaire
        comment_ref = doc_ref.collection('comments').document(comment_id)
        if not comment_ref.get().exists:
            return JsonResponse({'error': 'Commentaire non trouvé'}, status=404)

        comment_ref.delete()

        # Décrémenter le compteur
        doc_ref.update({'commentsCount': firestore.Increment(-1), 'updatedAt': datetime.utcnow()})

        logger.info(f"Comment {comment_id} deleted from video {video_id}")
        return JsonResponse({'success': True, 'message': 'Commentaire supprimé'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== EXPORT JSON ====================

@login_required
def video_get_json(request, video_id):
    """Retourne le JSON d'une vidéo."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(VIDEOS_COLLECTION).document(video_id).get()

        if not doc.exists:
            return JsonResponse({'error': 'Vidéo non trouvée'}, status=404)

        data = doc.to_dict()
        data['id'] = doc.id

        for key in ['createdAt', 'updatedAt']:
            if key in data and data[key]:
                val = data[key]
                data[key] = val.isoformat() if hasattr(val, 'isoformat') else str(val)

        return JsonResponse(data, json_dumps_params={'indent': 2})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
