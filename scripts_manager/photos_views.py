"""
Vues CRUD pour la gestion des photos dans Firebase Storage
"""
import os
import io
import gc
import logging
from datetime import datetime, timedelta
from django.core.cache import cache
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from google.cloud import storage
from google.oauth2 import service_account
from PIL import Image, ImageOps
from config import FIREBASE_BUCKET_PROD, SERVICE_ACCOUNT_PATH_PROD
from .firebase_utils import get_service_account_path, get_firebase_bucket, get_storage_service_account_path
from .restaurants_views import get_firestore_client

logger = logging.getLogger(__name__)

PHOTOS_CACHE_PREFIX = 'photos_cache::'
PHOTOS_CACHE_TTL = int(os.getenv('PHOTOS_CACHE_TTL', 300))
PHOTOS_PAGE_SIZE = int(os.getenv('PHOTOS_PAGE_SIZE', 60))


def build_query_without_page(request):
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    return query_params.urlencode()

# Initialiser le client Storage
def get_storage_client(request=None):
    """
    Retourne un client Storage configuré.
    Toujours prod — les photos sont stockées uniquement sur le bucket prod.
    """
    try:
        service_account_path = get_storage_service_account_path()
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        return storage.Client(credentials=credentials, project=credentials.project_id)
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du client Storage : {e}")
        return None

# Obtenir les credentials pour la signature
def get_storage_credentials(request=None):
    """
    Retourne les credentials pour la signature d'URL.
    Toujours prod — les photos sont stockées uniquement sur le bucket prod.
    """
    try:
        service_account_path = get_storage_service_account_path()
        return service_account.Credentials.from_service_account_file(
            service_account_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
    except Exception as e:
        logger.error(f"Erreur lors du chargement des credentials : {e}")
        return None


@login_required
def photos_list(request):
    """Liste toutes les photos d'un dossier (Logos/ ou Photos restaurants/)"""
    try:
        folder = request.GET.get('folder', 'logos')  # 'logos' ou 'photos'
        search_query = request.GET.get('search', '').strip()  # Recherche par nom
        page_number = request.GET.get('page', 1)
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"

        # Inclure l'environnement dans la clé de cache
        from .firebase_utils import get_firebase_env_from_session
        env = get_firebase_env_from_session(request)
        cache_key = f"{PHOTOS_CACHE_PREFIX}{folder}_{env}"
        cached_photos = cache.get(cache_key)
        if cached_photos is None:
            client = get_storage_client(request)
            if not client:
                return render(request, 'scripts_manager/photos/list.html', {
                    'photos': [],
                    'folder': folder,
                    'error': 'Erreur de connexion à Firebase Storage',
                    'page_obj': None,
                    'results_count': 0,
                    'query_string': build_query_without_page(request)
                })
            
            bucket = client.bucket(get_firebase_bucket(request))
            
            if bucket.client != client:
                logger.warning("Le bucket n'utilise pas le bon client, recréation...")
                bucket = client.bucket(get_firebase_bucket(request))
            
            blobs = list(bucket.list_blobs(prefix=folder_path))
            
            logger.info(f"📸 Récupération des photos depuis {folder_path}: {len(blobs)} blobs trouvés")
            logger.info(f"🔑 Client utilisé: {client.project}")
            
            photos = []
            for blob in blobs:
                if blob.name.endswith('/'):
                    continue
                
                filename = blob.name.replace(folder_path, "")
                photos.append({
                    'name': filename,
                    'full_path': blob.name,
                    'size': blob.size or 0,
                    'content_type': blob.content_type or 'image/png',
                    'time_created': blob.time_created,
                    'updated': blob.updated,
                    'url': None
                })
            cache.set(cache_key, [dict(p) for p in photos], PHOTOS_CACHE_TTL)
        else:
            photos = [dict(p) for p in cached_photos]
        
        # Filtrer par recherche si une requête est fournie
        if search_query:
            search_lower = search_query.lower()
            photos = [p for p in photos if search_lower in p['name'].lower()]
            logger.info(f"🔍 Recherche '{search_query}': {len(photos)} résultat(s) trouvé(s)")
        
        # Trier par nom
        photos.sort(key=lambda x: x['name'])

        results_count = len(photos)
        paginator = Paginator(photos, PHOTOS_PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        page_photos = list(page_obj.object_list)
        
        context = {
            'photos': page_photos,
            'page_obj': page_obj,
            'folder': folder,
            'folder_path': folder_path,
            'folder_display': 'Logos' if folder == 'logos' else 'Photos restaurants',
            'search_query': search_query,
            'results_count': results_count,
            'query_string': build_query_without_page(request)
        }
        return render(request, 'scripts_manager/photos/list.html', context)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des photos: {e}")
        return render(request, 'scripts_manager/photos/list.html', {
            'photos': [],
            'folder': folder,
            'error': str(e),
            'page_obj': None,
            'results_count': 0,
            'query_string': build_query_without_page(request)
        })


@login_required
def photo_detail(request, folder, photo_name):
    """Affiche les détails d'une photo (retourne JSON pour API)"""
    try:
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        full_path = f"{folder_path}{photo_name}"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        blob = bucket.blob(full_path)
        
        if not blob.exists():
            return JsonResponse({'error': 'Photo non trouvée'}, status=404)
        
        blob.reload()
        
        # Générer une URL signée pour télécharger la photo
        try:
            # Le blob doit être associé au bucket qui a le bon client avec credentials
            download_url = blob.generate_signed_url(
                expiration=3600,  # 1 heure en secondes
                method='GET',
                version='v4'
            )
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'URL signée: {e}")
            import traceback
            logger.error(traceback.format_exc())
            download_url = None
        
        photo_data = {
            'name': photo_name,
            'full_path': full_path,
            'size': blob.size or 0,
            'content_type': blob.content_type or 'image/png',
            'time_created': blob.time_created.isoformat() if blob.time_created else None,
            'updated': blob.updated.isoformat() if blob.updated else None,
            'url': download_url  # Utiliser uniquement l'URL signée
        }
        
        return JsonResponse(photo_data)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la photo: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def photo_upload(request):
    """Upload une ou plusieurs nouvelles photos"""
    try:
        if 'photo_file' not in request.FILES:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        folder = request.POST.get('folder', 'logos')
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        
        # Récupérer tous les fichiers (support multiple)
        photo_files = request.FILES.getlist('photo_file')
        if not photo_files:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        # Traiter le premier fichier (pour compatibilité avec l'ancien code)
        photo_file = photo_files[0]
        filename = request.POST.get('filename', photo_file.name)
        
        # Si un nom personnalisé est fourni, l'utiliser uniquement pour le premier fichier
        # Sinon, utiliser le nom original de chaque fichier
        
        # Vérifier l'extension
        allowed_extensions = ['.png', '.jpg', '.jpeg', '.webp', '.gif']
        if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
            return JsonResponse({
                'error': f'Format non supporté. Formats acceptés: {", ".join(allowed_extensions)}'
            }, status=400)
        
        # Nettoyer le nom du fichier
        filename = filename.replace(' ', '_').replace('/', '_').replace('\\', '_')
        full_path = f"{folder_path}{filename}"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        blob = bucket.blob(full_path)
        
        # Définir le content type
        content_type = photo_file.content_type
        if not content_type:
            if filename.lower().endswith('.png'):
                content_type = 'image/png'
            elif filename.lower().endswith('.webp'):
                content_type = 'image/webp'
            elif filename.lower().endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
            else:
                content_type = 'image/png'
        
        # Upload du fichier
        photo_file.seek(0)  # S'assurer qu'on est au début du fichier
        blob.upload_from_file(photo_file, content_type=content_type)
        
        # Ne pas rendre public - on utilisera des URLs signées
        
        logger.info(f"✅ Photo uploadée: {full_path}")
        
        return JsonResponse({
            'success': True,
            'message': f'Photo uploadée avec succès: {filename}',
            'filename': filename,
            'full_path': full_path,
            'size': blob.size or 0
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'upload: {e}")
        return JsonResponse({'error': f'Erreur lors de l\'upload: {str(e)}'}, status=500)


@require_http_methods(["POST"])
@login_required
def photo_delete(request, folder, photo_name):
    """Supprime une photo"""
    try:
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        full_path = f"{folder_path}{photo_name}"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        blob = bucket.blob(full_path)
        
        if not blob.exists():
            return JsonResponse({'error': 'Photo non trouvée'}, status=404)
        
        blob.delete()
        
        logger.info(f"🗑️ Photo supprimée: {full_path}")
        
        return JsonResponse({
            'success': True,
            'message': f'Photo supprimée avec succès: {photo_name}'
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la suppression: {e}")
        return JsonResponse({'error': f'Erreur lors de la suppression: {str(e)}'}, status=500)


@login_required
@require_http_methods(["GET"])
def photo_get_url(request, folder, photo_name):
    """Génère une URL signée pour une photo spécifique (API)"""
    try:
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        full_path = f"{folder_path}{photo_name}"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        blob = bucket.blob(full_path)
        
        if not blob.exists():
            return JsonResponse({'error': 'Photo non trouvée'}, status=404)
        
        # Générer l'URL signée
        try:
            download_url = blob.generate_signed_url(
                expiration=3600,  # 1 heure en secondes
                method='GET',
                version='v4'
            )
            return JsonResponse({'url': download_url})
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'URL signée: {e}")
            return JsonResponse({'error': f'Erreur lors de la génération de l\'URL: {str(e)}'}, status=500)
            
    except Exception as e:
        logger.error(f"Erreur: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def photo_rename(request, folder, photo_name):
    """Renomme une photo"""
    try:
        new_name = request.POST.get('new_name', '').strip()
        if not new_name:
            return JsonResponse({'error': 'Nouveau nom requis'}, status=400)
        
        # Nettoyer le nom
        new_name = new_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        old_path = f"{folder_path}{photo_name}"
        new_path = f"{folder_path}{new_name}"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        old_blob = bucket.blob(old_path)
        
        if not old_blob.exists():
            return JsonResponse({'error': 'Photo non trouvée'}, status=404)
        
        # Copier vers le nouveau nom
        new_blob = bucket.copy_blob(old_blob, bucket, new_path)
        # Ne pas rendre public - on utilisera des URLs signées
        
        # Supprimer l'ancien
        old_blob.delete()
        
        logger.info(f"✏️ Photo renommée: {old_path} → {new_path}")
        
        return JsonResponse({
            'success': True,
            'message': f'Photo renommée avec succès: {photo_name} → {new_name}',
            'new_name': new_name
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du renommage: {e}")
        return JsonResponse({'error': f'Erreur lors du renommage: {str(e)}'}, status=500)


def optimize_image(img: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """Optimise une image (redimensionnement, rotation, etc.)"""
    # Auto-rotation basée sur EXIF
    try:
        img = ImageOps.exif_transpose(img)
    except:
        pass
    
    # Redimensionner si nécessaire
    if img.width > max_width or img.height > max_height:
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    
    # Convertir en RGB si nécessaire (pour WebP)
    if img.mode == 'RGBA':
        # Créer un fond blanc pour la transparence
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    return img


def convert_to_webp(image_data: bytes, max_width: int, max_height: int, quality: int) -> tuple:
    """Convertit une image en WebP optimisé"""
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            original_size = img.size
            optimized_img = optimize_image(img, max_width, max_height)
            
            webp_buffer = io.BytesIO()
            optimized_img.save(
                webp_buffer,
                format='WebP',
                quality=quality,
                method=6,
                optimize=True
            )
            webp_data = webp_buffer.getvalue()
            
            stats = {
                'original_size': len(image_data),
                'webp_size': len(webp_data),
                'original_dimensions': original_size,
                'webp_dimensions': optimized_img.size,
                'reduction_percent': ((len(image_data) - len(webp_data)) / len(image_data) * 100) if len(image_data) > 0 else 0
            }
            
            return webp_data, stats
    except Exception as e:
        logger.error(f"Erreur lors de la conversion: {e}")
        raise


@require_http_methods(["POST"])
@login_required
def photo_convert_png_to_webp(request):
    """Convertit tous les PNG en WebP optimisé dans Photos restaurants/"""
    try:
        folder_path = "Photos restaurants/"
        max_width = 1920
        max_height = 1920
        quality = 85
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        
        # Lister tous les PNG (via générateur pour éviter de charger tout en RAM)
        logger.info(f"🔍 Recherche des images PNG dans {folder_path}...")
        png_images = [
            blob for blob in bucket.list_blobs(prefix=folder_path)
            if not blob.name.endswith('/') and blob.name.lower().endswith('.png')
        ]

        logger.info(f"📊 {len(png_images)} images PNG trouvées")

        if not png_images:
            return JsonResponse({
                'success': True,
                'message': 'Aucune image PNG à convertir',
                'stats': {
                    'total': 0,
                    'converted': 0,
                    'errors': 0,
                    'total_original_size_mb': 0,
                    'total_webp_size_mb': 0,
                    'space_saved_mb': 0,
                    'overall_reduction_percent': 0
                }
            })

        BATCH_SIZE = 50  # Traiter par petits lots pour limiter l'usage RAM

        stats = {
            'total': len(png_images),
            'converted': 0,
            'errors': 0,
            'total_original_size': 0,
            'total_webp_size': 0,
            'space_saved': 0,
            'details': []
        }

        for i, png_blob in enumerate(png_images, 1):
            try:
                logger.info(f"🔄 [{i}/{len(png_images)}] Conversion: {png_blob.name}")

                png_data = png_blob.download_as_bytes()
                original_size = len(png_data)
                stats['total_original_size'] += original_size

                webp_data, conversion_stats = convert_to_webp(png_data, max_width, max_height, quality)
                webp_size = len(webp_data)
                stats['total_webp_size'] += webp_size
                stats['space_saved'] += (original_size - webp_size)

                webp_name = png_blob.name.replace('.png', '.webp').replace('.PNG', '.webp')
                webp_blob = bucket.blob(webp_name)
                webp_blob.upload_from_string(webp_data, content_type='image/webp')

                # Libérer la mémoire immédiatement après upload
                del png_data, webp_data

                # Supprimer le PNG original
                png_blob.delete()

                png_mb = original_size / (1024 * 1024)
                webp_mb = webp_size / (1024 * 1024)
                reduction = conversion_stats['reduction_percent']

                # Garder seulement les 10 derniers détails en mémoire
                if len(stats['details']) < 10:
                    stats['details'].append({
                        'name': png_blob.name.replace(folder_path, ''),
                        'original_size_mb': round(png_mb, 2),
                        'webp_size_mb': round(webp_mb, 2),
                        'reduction_percent': round(reduction, 1)
                    })

                logger.info(f"   ✅ Converti: {png_mb:.2f} MB → {webp_mb:.2f} MB (-{reduction:.1f}%)")
                stats['converted'] += 1

                # Forcer le garbage collector tous les 50 fichiers
                if i % BATCH_SIZE == 0:
                    gc.collect()
                    logger.info(f"   🧹 Nettoyage mémoire après {i} fichiers")

            except Exception as e:
                logger.error(f"   ❌ Erreur PNG {png_blob.name}: {e}")
                stats['errors'] += 1
        
        total_mb = stats['total_original_size'] / (1024 * 1024)
        webp_total_mb = stats['total_webp_size'] / (1024 * 1024)
        space_saved_mb = stats['space_saved'] / (1024 * 1024)
        overall_reduction = (stats['space_saved'] / stats['total_original_size'] * 100) if stats['total_original_size'] > 0 else 0
        
        logger.info(f"✅ Conversion terminée: {stats['converted']}/{stats['total']} converties")
        logger.info(f"💾 Espace économisé: {space_saved_mb:.2f} MB (-{overall_reduction:.1f}%)")
        
        return JsonResponse({
            'success': True,
            'message': f'{stats["converted"]} image(s) convertie(s) avec succès',
            'stats': {
                'total': stats['total'],
                'converted': stats['converted'],
                'errors': stats['errors'],
                'total_original_size_mb': round(total_mb, 2),
                'total_webp_size_mb': round(webp_total_mb, 2),
                'space_saved_mb': round(space_saved_mb, 2),
                'overall_reduction_percent': round(overall_reduction, 1),
                'details': stats['details'][:10]  # Limiter à 10 détails pour éviter une réponse trop lourde
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la conversion PNG → WebP: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({'error': f'Erreur lors de la conversion: {str(e)}'}, status=500)


@require_http_methods(["POST"])
@login_required
def photo_bulk_delete(request):
    """Supprime plusieurs photos en une seule requête"""
    try:
        import json
        data = json.loads(request.body)
        folder = data.get('folder', 'logos')
        photo_names = data.get('photo_names', [])
        
        if not photo_names:
            return JsonResponse({'error': 'Aucune photo sélectionnée'}, status=400)
        
        folder_path = "Logos/" if folder == "logos" else "Photos restaurants/"
        
        client = get_storage_client(request)
        if not client:
            return JsonResponse({'error': 'Erreur de connexion à Firebase Storage'}, status=500)
        
        bucket = client.bucket(get_firebase_bucket(request))
        
        deleted = 0
        errors = 0
        error_details = []
        
        for photo_name in photo_names:
            try:
                full_path = f"{folder_path}{photo_name}"
                blob = bucket.blob(full_path)
                
                if blob.exists():
                    blob.delete()
                    logger.info(f"🗑️ Photo supprimée: {full_path}")
                    deleted += 1
                else:
                    logger.warning(f"⚠️ Photo non trouvée: {full_path}")
                    errors += 1
                    error_details.append(f"{photo_name} (non trouvée)")
            except Exception as e:
                logger.error(f"❌ Erreur lors de la suppression de {photo_name}: {e}")
                errors += 1
                error_details.append(f"{photo_name} ({str(e)})")
        
        return JsonResponse({
            'success': True,
            'message': f'{deleted} photo(s) supprimée(s) avec succès',
            'deleted': deleted,
            'errors': errors,
            'error_details': error_details[:10]  # Limiter à 10 détails
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la suppression groupée: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({'error': f'Erreur lors de la suppression groupée: {str(e)}'}, status=500)


PHOTOS_RESTAURANTS_PREFIX = "Photos restaurants/"


@login_required
def photo_export_restaurants_without_webp(request):
    """
    Exporte la liste des restaurants sans aucune photo .webp sur le bucket PROD.
    IDs depuis Firestore (env session), photos lues depuis le bucket PROD.
    Retourne un fichier Excel en téléchargement.
    """
    from openpyxl import Workbook
    from google.oauth2 import service_account

    try:
        # IDs restaurants depuis Firestore (env session)
        db = get_firestore_client(request)
        restaurant_ids = set()
        for doc in db.collection("restaurants").stream():
            restaurant_ids.add(doc.id)

        if not restaurant_ids:
            from django.contrib import messages
            messages.warning(request, "Aucun restaurant dans Firestore.")
            return redirect("scripts_manager:photos_list")

        # IDs avec au moins une photo .webp dans le bucket PROD
        if not os.path.exists(SERVICE_ACCOUNT_PATH_PROD):
            from django.contrib import messages
            messages.error(request, "Credentials PROD introuvables.")
            return redirect("scripts_manager:photos_list")

        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH_PROD,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = storage.Client(credentials=creds, project=creds.project_id)
        bucket = client.bucket(FIREBASE_BUCKET_PROD)
        blobs = list(bucket.list_blobs(prefix=PHOTOS_RESTAURANTS_PREFIX))
        ids_with_webp = set()
        for blob in blobs:
            name = blob.name
            if not name.lower().endswith(".webp"):
                continue
            rel = name[len(PHOTOS_RESTAURANTS_PREFIX) :].lstrip("/")
            base = rel.replace(".webp", "").replace(".WEBP", "")
            for i in range(len(base), 0, -1):
                prefix, suffix = base[:i], base[i:]
                if suffix.isdigit():
                    ids_with_webp.add(prefix)
                    break

        without_webp = sorted(restaurant_ids - ids_with_webp)

        # Excel en mémoire
        wb = Workbook()
        ws = wb.active
        ws.title = "Sans_photo_webp"
        ws.append(["Restaurant_ID", "Remarque"])
        remarque = "Aucune photo .webp sur le bucket Storage PROD"
        for rid in without_webp:
            ws.append([rid, remarque])
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 55

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        buffer_value = buffer.getvalue()

        from django.utils import timezone
        filename = f"restaurants_sans_photo_webp_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            buffer_value,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.error(f"❌ Export restaurants sans photo WebP: {e}")
        import traceback
        logger.error(traceback.format_exc())
        from django.contrib import messages
        messages.error(request, f"Erreur lors de l'export : {str(e)}")
        return redirect("scripts_manager:photos_list")

