"""
Vues CRUD pour la gestion des restaurants Firestore
"""
import os
import json
import logging
from pathlib import Path
from django.core.cache import cache
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from google.cloud import firestore
from google.cloud import storage
from google.oauth2 import service_account
from config import FIREBASE_BUCKET
from .firebase_utils import get_service_account_path

logger = logging.getLogger(__name__)

RESTAURANTS_CACHE_KEY = 'restaurants_collection_cache_v1'
RESTAURANTS_CACHE_TTL = int(os.getenv('RESTAURANTS_CACHE_TTL', 300))
RESTAURANTS_PAGE_SIZE = int(os.getenv('RESTAURANTS_PAGE_SIZE', 50))
RESTAURANT_MEDIA_CACHE_PREFIX = 'restaurant_media_cache::'
RESTAURANT_MEDIA_CACHE_TTL = int(os.getenv('RESTAURANT_MEDIA_CACHE_TTL', 300))
MISSING_PHOTOS_CACHE_KEY = 'restaurants_missing_photos_cache'
MISSING_LOGOS_CACHE_KEY = 'restaurants_missing_logos_cache'
MISSING_CACHE_TTL = int(os.getenv('RESTAURANTS_MISSING_CACHE_TTL', 300))


def build_query_without_page(request):
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    return query_params.urlencode()

# Initialiser le client Firestore
def get_firestore_client(request=None):
    """
    Retourne un client Firestore configuré
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    service_account_path = get_service_account_path(request)
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = service_account_path
    return firestore.Client()


# Initialiser le client Storage
def get_storage_client(request=None):
    """
    Retourne un client Storage configuré
    
    Args:
        request: Objet request Django (optionnel) pour déterminer l'environnement
    """
    try:
        service_account_path = get_service_account_path(request)
        credentials = service_account.Credentials.from_service_account_file(
            service_account_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        return storage.Client(credentials=credentials, project=credentials.project_id)
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du client Storage : {e}")
        return None


def get_restaurants_with_missing_photos():
    """Retourne la liste des IDs de restaurants avec photos manquantes"""
    try:
        cached = cache.get(MISSING_PHOTOS_CACHE_KEY)
        if cached is not None:
            return cached

        # Note: Cette fonction n'a pas accès à request, donc utilisera l'env par défaut
        client = get_storage_client()
        if not client:
            return set()
        
        bucket = client.bucket(FIREBASE_BUCKET)
        prefix = "Photos restaurants/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        # Récupérer tous les restaurants depuis Firestore
        firestore_client = get_firestore_client()
        restaurants_ref = firestore_client.collection('restaurants')
        restaurant_ids = set()
        for doc in restaurants_ref.stream():
            restaurant_ids.add(doc.id)
        
        # Extraire les photos par restaurant
        restaurant_photos = {}
        for blob in blobs:
            filename = blob.name.replace(prefix, "")
            if filename.lower().endswith('.webp'):
                base_name = filename.replace('.webp', '').replace('.WEBP', '')
                restaurant_id = None
                photo_number = None
                
                for i in range(len(base_name), 0, -1):
                    if base_name[:i] in restaurant_ids:
                        restaurant_id = base_name[:i]
                        photo_number = base_name[i:]
                        break
                
                if restaurant_id and photo_number.isdigit():
                    if restaurant_id not in restaurant_photos:
                        restaurant_photos[restaurant_id] = set()
                    restaurant_photos[restaurant_id].add(int(photo_number))
        
        # Identifier les restaurants avec photos manquantes
        missing_photos_ids = set()
        for restaurant_id in restaurant_ids:
            if restaurant_id in restaurant_photos:
                existing_photos = restaurant_photos[restaurant_id]
                max_photo = max(existing_photos) if existing_photos else 0
                # Vérifier les photos manquantes (2 à max_photo)
                for photo_num in range(2, max_photo + 1):
                    if photo_num not in existing_photos:
                        missing_photos_ids.add(restaurant_id)
                        break
            else:
                # Restaurant sans aucune photo
                missing_photos_ids.add(restaurant_id)
        
        cache.set(MISSING_PHOTOS_CACHE_KEY, missing_photos_ids, MISSING_CACHE_TTL)
        return missing_photos_ids
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des photos manquantes : {e}")
        return set()


def get_restaurants_with_missing_logos():
    """Retourne la liste des IDs de restaurants sans logo"""
    try:
        cached = cache.get(MISSING_LOGOS_CACHE_KEY)
        if cached is not None:
            return cached

        client = get_storage_client(request)
        if not client:
            return set()
        
        bucket = client.bucket(FIREBASE_BUCKET)
        prefix = "Logos/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        
        # Récupérer tous les restaurants depuis Firestore
        firestore_client = get_firestore_client()
        restaurants_ref = firestore_client.collection('restaurants')
        restaurant_ids = set()
        for doc in restaurants_ref.stream():
            restaurant_ids.add(doc.id)
        
        # Extraire les logos
        logo_ids = set()
        for blob in blobs:
            filename = blob.name.replace(prefix, "")
            if filename.lower().endswith('.png'):
                logo_id = filename.replace('.png', '').replace('.PNG', '')
                logo_ids.add(logo_id)
        
        # Identifier les restaurants sans logo
        missing_logos_ids = set()
        for restaurant_id in restaurant_ids:
            found_logo = False
            for logo_id in logo_ids:
                if logo_id.startswith(restaurant_id) and logo_id[len(restaurant_id):].isdigit():
                    found_logo = True
                    break
            if not found_logo:
                missing_logos_ids.add(restaurant_id)
        
        cache.set(MISSING_LOGOS_CACHE_KEY, missing_logos_ids, MISSING_CACHE_TTL)
        return missing_logos_ids
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des logos manquants : {e}")
        return set()


def get_restaurant_media_info(restaurant_ids):
    """Récupère les informations sur les photos et logos pour chaque restaurant
    
    Retourne un dictionnaire: {
        restaurant_id: {
            'has_logo': bool,
            'logo_count': int,
            'photo_count': int,
            'photos': [list of photo numbers]
        }
    }
    """
    try:
        client = get_storage_client(request)
        if not client:
            return {}
        
        bucket = client.bucket(FIREBASE_BUCKET)
        media_info = {rid: {'has_logo': False, 'logo_count': 0, 'photo_count': 0, 'photos': []} for rid in restaurant_ids}
        
        # Récupérer les logos
        logos_prefix = "Logos/"
        logo_blobs = list(bucket.list_blobs(prefix=logos_prefix))
        
        for blob in logo_blobs:
            filename = blob.name.replace(logos_prefix, "")
            if filename.lower().endswith('.png'):
                logo_id = filename.replace('.png', '').replace('.PNG', '')
                # Trouver le restaurant correspondant
                for restaurant_id in restaurant_ids:
                    if logo_id.startswith(restaurant_id) and logo_id[len(restaurant_id):].isdigit():
                        media_info[restaurant_id]['has_logo'] = True
                        media_info[restaurant_id]['logo_count'] += 1
                        break
        
        # Récupérer les photos
        photos_prefix = "Photos restaurants/"
        photo_blobs = list(bucket.list_blobs(prefix=photos_prefix))
        
        for blob in photo_blobs:
            filename = blob.name.replace(photos_prefix, "")
            if filename.lower().endswith('.webp'):
                base_name = filename.replace('.webp', '').replace('.WEBP', '')
                # Trouver le restaurant correspondant
                restaurant_id = None
                photo_number = None
                
                for i in range(len(base_name), 0, -1):
                    if base_name[:i] in restaurant_ids:
                        restaurant_id = base_name[:i]
                        photo_number = base_name[i:]
                        break
                
                if restaurant_id and photo_number.isdigit():
                    photo_num = int(photo_number)
                    if photo_num not in media_info[restaurant_id]['photos']:
                        media_info[restaurant_id]['photos'].append(photo_num)
                        media_info[restaurant_id]['photo_count'] = len(media_info[restaurant_id]['photos'])
        
        return media_info
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des infos média : {e}")
        return {}


@login_required
def restaurants_list(request):
    """Liste tous les restaurants avec possibilité de recherche"""
    try:
        search_query = request.GET.get('search', '').strip()
        filter_type = request.GET.get('filter', '').strip()  # 'missing_photos' ou 'missing_logos'
        page_number = request.GET.get('page', 1)
        logger.info(f"🔍 Recherche demandée: '{search_query}', Filtre: '{filter_type}'")

        # Inclure l'environnement dans la clé de cache
        from .firebase_utils import get_firebase_env_from_session
        env = get_firebase_env_from_session(request)
        cache_key = f"{RESTAURANTS_CACHE_KEY}_{env}"
        
        cached_restaurants = cache.get(cache_key)
        if cached_restaurants is None:
            client = get_firestore_client(request)
            restaurants_ref = client.collection('restaurants')
            restaurants = []
            for doc in restaurants_ref.stream():
                restaurant_data = doc.to_dict()
                restaurant_data['id'] = doc.id

                if 'name' not in restaurant_data:
                    restaurant_data['name'] = (
                        restaurant_data.get('Name') or 
                        restaurant_data.get('nom') or 
                        restaurant_data.get('NOM') or 
                        None
                    )

                if 'address' not in restaurant_data:
                    restaurant_data['address'] = restaurant_data.get('adresse') or restaurant_data.get('Address')

                if 'raw_name' not in restaurant_data:
                    restaurant_data['raw_name'] = restaurant_data.get('Raw_name') or restaurant_data.get('rawName')

                restaurants.append(restaurant_data)

            cache.set(cache_key, [dict(r) for r in restaurants], RESTAURANTS_CACHE_TTL)
        else:
            restaurants = [dict(r) for r in cached_restaurants]
        
        logger.info(f"📊 Total restaurants chargés: {len(restaurants)}")
        if restaurants:
            sample_restaurant = restaurants[0]
            # Vérifier différentes variantes du champ Name
            name_variants = {
                'Name': sample_restaurant.get('Name'),
                'name': sample_restaurant.get('name'),
                'NOM': sample_restaurant.get('NOM'),
                'nom': sample_restaurant.get('nom'),
            }
            logger.info(f"📝 Exemple de restaurant - ID: {sample_restaurant.get('id')}")
            logger.info(f"📝 Variantes du champ nom: {name_variants}")
            logger.info(f"📝 Toutes les clés disponibles: {list(sample_restaurant.keys())}")
            
            # Chercher le restaurant ABR spécifiquement
            abr_restaurant = next((r for r in restaurants if r.get('id') == 'ABR'), None)
            if abr_restaurant:
                logger.info(f"🔍 Restaurant ABR trouvé - Toutes les clés: {list(abr_restaurant.keys())}")
                logger.info(f"🔍 Restaurant ABR - Name: {abr_restaurant.get('Name')}, name: {abr_restaurant.get('name')}")
            
            # Déterminer le bon champ à utiliser
            name_field = None
            if sample_restaurant.get('name'):
                name_field = 'name'
            elif sample_restaurant.get('Name'):
                name_field = 'Name'
            elif sample_restaurant.get('nom'):
                name_field = 'nom'
            elif sample_restaurant.get('NOM'):
                name_field = 'NOM'
            logger.info(f"✅ Champ nom détecté: '{name_field}'")
        
        # Appliquer les filtres (photos/logos manquants)
        if filter_type == 'missing_photos':
            missing_ids = get_restaurants_with_missing_photos()
            logger.info(f"📸 Restaurants avec photos manquantes: {len(missing_ids)}")
            restaurants = [r for r in restaurants if r.get('id') in missing_ids]
        elif filter_type == 'missing_logos':
            missing_ids = get_restaurants_with_missing_logos()
            logger.info(f"🖼️ Restaurants sans logo: {len(missing_ids)}")
            restaurants = [r for r in restaurants if r.get('id') in missing_ids]
        
        # Filtrer par Name si une recherche est effectuée (recherche approximative)
        if search_query:
            search_lower = search_query.lower().strip()
            search_words = search_lower.split()
            
            def levenshtein_distance(s1, s2):
                """Calcule la distance de Levenshtein entre deux chaînes"""
                if len(s1) < len(s2):
                    return levenshtein_distance(s2, s1)
                if len(s2) == 0:
                    return len(s1)
                
                previous_row = range(len(s2) + 1)
                for i, c1 in enumerate(s1):
                    current_row = [i + 1]
                    for j, c2 in enumerate(s2):
                        insertions = previous_row[j + 1] + 1
                        deletions = current_row[j] + 1
                        substitutions = previous_row[j] + (c1 != c2)
                        current_row.append(min(insertions, deletions, substitutions))
                    previous_row = current_row
                
                return previous_row[-1]
            
            def fuzzy_match(restaurant_name, search_query, search_words):
                """Recherche approximative sur le nom du restaurant"""
                if not restaurant_name:
                    logger.debug(f"  ❌ Restaurant sans nom: {restaurant_name}")
                    return False
                
                name_lower = str(restaurant_name).lower()
                logger.debug(f"  🔎 Comparaison: '{search_lower}' vs '{name_lower}'")
                
                # 1. Correspondance exacte (priorité maximale)
                if search_lower == name_lower:
                    logger.debug(f"  ✅ Correspondance exacte trouvée: '{name_lower}'")
                    return True
                
                # 2. Le nom commence par la recherche
                if name_lower.startswith(search_lower):
                    logger.debug(f"  ✅ Nom commence par recherche: '{name_lower}'")
                    return True
                
                # 3. La recherche est contenue dans le nom
                if search_lower in name_lower:
                    logger.debug(f"  ✅ Recherche contenue dans nom: '{name_lower}'")
                    return True
                
                # 4. Tous les mots de la recherche sont présents dans le nom (ordre flexible)
                if len(search_words) > 1 and all(word in name_lower for word in search_words if len(word) > 2):
                    logger.debug(f"  ✅ Tous les mots présents: '{name_lower}'")
                    return True
                
                # 5. Recherche par similarité avec distance de Levenshtein
                # Pour chaque mot du nom, vérifier la similarité
                name_words = name_lower.split()
                for name_word in name_words:
                    # Distance de Levenshtein
                    distance = levenshtein_distance(search_lower, name_word)
                    max_distance = max(1, len(search_lower) // 3)  # Tolérance adaptative
                    if distance <= max_distance:
                        logger.debug(f"  ✅ Distance Levenshtein OK ({distance}/{max_distance}): '{name_word}' dans '{name_lower}'")
                        return True
                    else:
                        logger.debug(f"  ⚠️ Distance Levenshtein trop grande ({distance}/{max_distance}): '{name_word}'")
                
                # 6. Vérifier si la recherche est proche du début d'un mot du nom
                for name_word in name_words:
                    if len(search_lower) <= len(name_word):
                        # Vérifier les sous-chaînes du mot
                        for i in range(len(name_word) - len(search_lower) + 1):
                            substring = name_word[i:i+len(search_lower)]
                            distance = levenshtein_distance(search_lower, substring)
                            if distance <= max(1, len(search_lower) // 4):
                                logger.debug(f"  ✅ Sous-chaîne similaire trouvée: '{substring}' dans '{name_word}'")
                                return True
                
                # 7. Au moins un mot de la recherche est présent (recherche très permissive)
                if any(word in name_lower for word in search_words if len(word) > 2):
                    logger.debug(f"  ✅ Au moins un mot présent: '{name_lower}'")
                    return True
                
                logger.debug(f"  ❌ Aucune correspondance pour: '{name_lower}'")
                return False
            
            logger.info(f"🔍 Début du filtrage avec '{search_lower}' ({len(search_words)} mots)")
            restaurants_before = len(restaurants)
            
            # Sauvegarder la liste originale pour les logs de debug
            restaurants_original = restaurants.copy()
            
            # Rechercher dans raw_name (priorité) ou name
            def get_restaurant_search_name(restaurant):
                """Récupère le nom pour la recherche (raw_name en priorité)"""
                return (restaurant.get('raw_name') or 
                       restaurant.get('Raw_name') or 
                       restaurant.get('rawName') or
                       restaurant.get('name') or 
                       restaurant.get('Name') or 
                       restaurant.get('nom') or 
                       restaurant.get('NOM') or 
                       None)
            
            restaurants = [
                r for r in restaurants 
                if get_restaurant_search_name(r) and fuzzy_match(get_restaurant_search_name(r), search_lower, search_words)
            ]
            
            restaurants_after = len(restaurants)
            logger.info(f"📊 Résultats: {restaurants_before} → {restaurants_after} restaurants")
            
            if restaurants_after == 0:
                logger.warning(f"⚠️ Aucun résultat trouvé pour '{search_query}'")
                # Afficher quelques exemples de noms pour déboguer
                def get_name_for_log(r):
                    return (r.get('raw_name') or 
                           r.get('Raw_name') or 
                           r.get('rawName') or
                           r.get('name') or 
                           r.get('Name') or 
                           r.get('nom') or 
                           r.get('NOM') or 
                           'N/A')
                
                sample_names = [get_name_for_log(r) for r in restaurants_original[:10]]
                logger.info(f"📝 Exemples de raw_name/name dans la base (10 premiers): {sample_names}")
                # Afficher aussi les restaurants sans nom
                restaurants_without_name = [r.get('id', 'N/A') for r in restaurants_original[:10] if get_name_for_log(r) == 'N/A']
                if restaurants_without_name:
                    logger.warning(f"⚠️ Restaurants sans champ raw_name/name (toutes variantes): {restaurants_without_name[:5]}")
                
                # Vérifier spécifiquement le restaurant ABR
                abr_restaurant = next((r for r in restaurants_original if r.get('id') == 'ABR'), None)
                if abr_restaurant:
                    search_name = get_restaurant_search_name(abr_restaurant)
                    logger.info(f"🔍 Restaurant ABR - raw_name: {abr_restaurant.get('raw_name')}, name: {abr_restaurant.get('name')}, Raw_name: {abr_restaurant.get('Raw_name')}")
                    logger.info(f"🔍 Test de correspondance avec '{search_lower}': {fuzzy_match(search_name, search_lower, search_words) if search_name else 'Pas de nom'}")
        
        # Trier par raw_name si disponible (priorité), sinon name
        def get_name_for_sort(r):
            name = (r.get('raw_name') or 
                   r.get('Raw_name') or 
                   r.get('rawName') or
                   r.get('name') or 
                   r.get('Name') or 
                   r.get('nom') or 
                   r.get('NOM') or 
                   '')
            return name.lower() if isinstance(name, str) else ''
        
        restaurants.sort(key=get_name_for_sort)

        results_count = len(restaurants)
        paginator = Paginator(restaurants, RESTAURANTS_PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        page_restaurants = list(page_obj.object_list)

        media_info = get_restaurant_media_info({r.get('id') for r in page_restaurants})
        default_media = {'has_logo': False, 'logo_count': 0, 'photo_count': 0, 'photos': []}
        for restaurant in page_restaurants:
            info = media_info.get(restaurant.get('id')) or default_media
            restaurant['has_logo'] = info.get('has_logo', False)
            restaurant['logo_count'] = info.get('logo_count', 0)
            restaurant['photo_count'] = info.get('photo_count', 0)
            restaurant['photos'] = info.get('photos', [])
        
        context = {
            'restaurants': page_restaurants,
            'page_obj': page_obj,
            'search_query': search_query,
            'filter_type': filter_type,
            'results_count': results_count,
            'query_string': build_query_without_page(request)
        }
        return render(request, 'scripts_manager/restaurants/list.html', context)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des restaurants: {e}")
        return render(request, 'scripts_manager/restaurants/list.html', {
            'restaurants': [],
            'error': str(e),
            'search_query': '',
            'filter_type': '',
            'page_obj': None,
            'results_count': 0,
            'query_string': build_query_without_page(request)
        })


@login_required
def restaurant_detail(request, restaurant_id):
    """Affiche les détails d'un restaurant"""
    try:
        client = get_firestore_client(request)
        restaurant_ref = client.collection('restaurants').document(restaurant_id)
        restaurant_doc = restaurant_ref.get()
        
        if not restaurant_doc.exists:
            return JsonResponse({'error': 'Restaurant non trouvé'}, status=404)
        
        restaurant_data = restaurant_doc.to_dict()
        restaurant_data['id'] = restaurant_id
        
        # Normaliser les champs
        if 'name' not in restaurant_data:
            restaurant_data['name'] = (
                restaurant_data.get('Name') or 
                restaurant_data.get('nom') or 
                restaurant_data.get('NOM') or 
                None
            )
        if 'address' not in restaurant_data:
            restaurant_data['address'] = restaurant_data.get('adresse') or restaurant_data.get('Address')
        if 'raw_name' not in restaurant_data:
            restaurant_data['raw_name'] = restaurant_data.get('Raw_name') or restaurant_data.get('rawName')
        
        context = {
            'restaurant': restaurant_data
        }
        return render(request, 'scripts_manager/restaurants/detail.html', context)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du restaurant: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def restaurant_create(request):
    """Affiche le formulaire de création ou crée un restaurant"""
    if request.method == 'GET':
        return render(request, 'scripts_manager/restaurants/form.html', {
            'action': 'create',
            'restaurant': {}
        })
    
    elif request.method == 'POST':
        try:
            client = get_firestore_client(request)
            restaurants_ref = client.collection('restaurants')
            
            # Récupérer les données du formulaire
            data = {}
            custom_fields = {}
            
            for key, value in request.POST.items():
                if key == 'csrfmiddlewaretoken':
                    continue
                
                # Gérer les champs personnalisés
                if key.startswith('custom_field_name_'):
                    field_index = key.replace('custom_field_name_', '')
                    field_name = value.strip()
                    field_value_key = f'custom_field_value_{field_index}'
                    if field_value_key in request.POST and field_name:
                        field_value = request.POST[field_value_key].strip()
                        if field_value:
                            custom_fields[field_name] = field_value
                    continue
                
                if key.startswith('custom_field_value_'):
                    continue
                
                # Gérer les champs normaux
                if value:
                    # Gérer les types de données
                    if value.lower() == 'true':
                        data[key] = True
                    elif value.lower() == 'false':
                        data[key] = False
                    elif value.isdigit():
                        data[key] = int(value)
                    elif value.replace('.', '', 1).isdigit():
                        data[key] = float(value)
                    else:
                        data[key] = value
            
            # Fusionner les champs personnalisés
            data.update(custom_fields)
            
            # Créer le restaurant
            doc_ref = restaurants_ref.add(data)
            restaurant_id = doc_ref[1].id
            
            return redirect('scripts_manager:restaurant_detail', restaurant_id=restaurant_id)
        except Exception as e:
            logger.error(f"Erreur lors de la création du restaurant: {e}")
            return render(request, 'scripts_manager/restaurants/form.html', {
                'action': 'create',
                'restaurant': {},
                'error': str(e)
            })


@login_required
def restaurant_edit(request, restaurant_id):
    """Affiche le formulaire d'édition ou met à jour un restaurant"""
    try:
        client = get_firestore_client(request)
        restaurant_ref = client.collection('restaurants').document(restaurant_id)
        restaurant_doc = restaurant_ref.get()
        
        if not restaurant_doc.exists:
            return JsonResponse({'error': 'Restaurant non trouvé'}, status=404)
        
        restaurant_data = restaurant_doc.to_dict()
        restaurant_data['id'] = restaurant_id
        
        if request.method == 'GET':
            # Normaliser les champs avant d'afficher le formulaire
            if 'name' not in restaurant_data:
                restaurant_data['name'] = (
                    restaurant_data.get('Name') or 
                    restaurant_data.get('nom') or 
                    restaurant_data.get('NOM') or 
                    None
                )
            if 'address' not in restaurant_data:
                restaurant_data['address'] = restaurant_data.get('adresse') or restaurant_data.get('Address')
            if 'raw_name' not in restaurant_data:
                restaurant_data['raw_name'] = restaurant_data.get('Raw_name') or restaurant_data.get('rawName')
            
            return render(request, 'scripts_manager/restaurants/form.html', {
                'action': 'edit',
                'restaurant': restaurant_data
            })
        
        elif request.method == 'POST':
            # Récupérer les données du formulaire
            data = {}
            custom_fields = {}
            
            for key, value in request.POST.items():
                if key == 'csrfmiddlewaretoken':
                    continue
                
                # Gérer les champs personnalisés
                if key.startswith('custom_field_name_'):
                    field_index = key.replace('custom_field_name_', '')
                    field_name = value.strip()
                    field_value_key = f'custom_field_value_{field_index}'
                    if field_value_key in request.POST and field_name:
                        field_value = request.POST[field_value_key].strip()
                        if field_value:
                            custom_fields[field_name] = field_value
                    continue
                
                if key.startswith('custom_field_value_'):
                    continue
                
                # Gérer les champs normaux
                if value:
                    # Gérer les types de données
                    if value.lower() == 'true':
                        data[key] = True
                    elif value.lower() == 'false':
                        data[key] = False
                    elif value.isdigit():
                        data[key] = int(value)
                    elif value.replace('.', '', 1).isdigit():
                        data[key] = float(value)
                    else:
                        data[key] = value
                else:
                    # Si la valeur est vide, on peut la supprimer ou la mettre à None
                    data[key] = None
            
            # Fusionner les champs personnalisés
            data.update(custom_fields)
            
            # Mettre à jour le restaurant
            restaurant_ref.update(data)
            
            return redirect('scripts_manager:restaurant_detail', restaurant_id=restaurant_id)
            
    except Exception as e:
        logger.error(f"Erreur lors de l'édition du restaurant: {e}")
        return render(request, 'scripts_manager/restaurants/form.html', {
            'action': 'edit',
            'restaurant': restaurant_data if 'restaurant_data' in locals() else {},
            'error': str(e)
        })


@require_http_methods(["POST"])
@login_required
def restaurant_delete(request, restaurant_id):
    """Supprime un restaurant"""
    try:
        client = get_firestore_client(request)
        restaurant_ref = client.collection('restaurants').document(restaurant_id)
        restaurant_doc = restaurant_ref.get()
        
        if not restaurant_doc.exists:
            return JsonResponse({'error': 'Restaurant non trouvé'}, status=404)
        
        # Supprimer le restaurant
        restaurant_ref.delete()
        
        return redirect('scripts_manager:restaurants_list')
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du restaurant: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def restaurant_get_json(request, restaurant_id):
    """Retourne un restaurant en JSON (pour API)"""
    try:
        client = get_firestore_client(request)
        restaurant_ref = client.collection('restaurants').document(restaurant_id)
        restaurant_doc = restaurant_ref.get()
        
        if not restaurant_doc.exists:
            return JsonResponse({'error': 'Restaurant non trouvé'}, status=404)
        
        restaurant_data = restaurant_doc.to_dict()
        restaurant_data['id'] = restaurant_id
        
        return JsonResponse(restaurant_data)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du restaurant: {e}")
        return JsonResponse({'error': str(e)}, status=500)

