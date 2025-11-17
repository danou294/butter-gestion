"""
Vues Django pour les notifications push
"""
import logging
import json
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from . import notifications_services
from .users_views import fetch_firestore_users, fetch_auth_users, fetch_fcm_tokens, extract_phone

logger = logging.getLogger(__name__)


@login_required
def notifications_index(request):
    """Page principale pour l'envoi de notifications"""
    # Récupérer la liste des utilisateurs pour le sélecteur de groupe
    firestore_users = fetch_firestore_users()
    auth_users = fetch_auth_users()
    fcm_tokens = fetch_fcm_tokens()  # Dict[userId, List[dict]]
    
    # Créer une liste d'utilisateurs avec leurs infos
    # UNIQUEMENT ceux qui ont un token FCM
    users_list = []
    
    # Ne garder que les UIDs qui ont un token FCM
    uids_with_tokens = set(fcm_tokens.keys())
    
    for uid in uids_with_tokens:
        profile = firestore_users.get(uid, {})
        auth_user = auth_users.get(uid)
        
        # Accéder aux attributs de UserRecord (pas un dict)
        prenom = profile.get('prenom') or (auth_user.display_name if auth_user else None) or 'Utilisateur'
        email = (auth_user.email if auth_user else None) or profile.get('email') or 'N/A'
        
        # Vérifier qu'il y a au moins un token valide
        tokens_for_user = fcm_tokens.get(uid, [])
        has_valid_token = any(token_data.get('token') for token_data in tokens_for_user)
        
        if has_valid_token:
            users_list.append({
                'uid': uid,
                'prenom': prenom,
                'email': email,
            })
    
    # Trier par prénom
    users_list.sort(key=lambda x: x['prenom'])
    
    context = {
        'users': users_list,
    }
    return render(request, 'scripts_manager/notifications/index.html', context)


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def send_notification_to_all(request):
    """
    Envoie une notification à tous les utilisateurs (sans personnalisation)
    """
    try:
        data = json.loads(request.body)
        title = data.get('title')
        body = data.get('body')
        notification_data = data.get('data', {})
        
        # Validation
        if not title or not body:
            return JsonResponse({
                'error': 'Les champs title et body sont requis'
            }, status=400)
        
        response = notifications_services.send_push_notification_to_all(
            title, body, notification_data
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Notifications envoyées à tous les utilisateurs',
            'successCount': response['successCount'],
            'failureCount': response['failureCount'],
            'totalTokens': response.get('totalTokens', response['successCount'] + response['failureCount']),
        })
    except Exception as error:
        logger.error(f"Erreur: {error}")
        return JsonResponse({
            'error': 'Erreur lors de l\'envoi des notifications',
            'details': str(error),
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def send_notification_to_all_with_prenom(request):
    """
    Envoie une notification personnalisée à tous les utilisateurs avec leurs prénoms
    """
    try:
        data = json.loads(request.body)
        title = data.get('title')
        body = data.get('body')
        notification_data = data.get('data', {})
        
        # Validation
        if not title or not body:
            return JsonResponse({
                'error': 'Les champs title et body sont requis'
            }, status=400)
        
        response = notifications_services.send_push_notification_to_all_with_prenom(
            title, body, notification_data
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Notifications personnalisées envoyées à tous les utilisateurs',
            'successCount': response['successCount'],
            'failureCount': response['failureCount'],
            'totalTokens': response.get('totalTokens', response['successCount'] + response['failureCount']),
        })
    except Exception as error:
        logger.error(f"Erreur: {error}")
        return JsonResponse({
            'error': 'Erreur lors de l\'envoi des notifications',
            'details': str(error),
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def send_notification_to_group(request):
    """
    Envoie une notification à un groupe d'utilisateurs spécifiques
    """
    try:
        data = json.loads(request.body)
        user_ids = data.get('userIds')
        title = data.get('title')
        body = data.get('body')
        notification_data = data.get('data', {})
        
        # Validation
        if not user_ids or not isinstance(user_ids, list) or len(user_ids) == 0:
            return JsonResponse({
                'error': 'Le champ userIds doit être un tableau non vide'
            }, status=400)
        
        if not title or not body:
            return JsonResponse({
                'error': 'Les champs title et body sont requis'
            }, status=400)
        
        response = notifications_services.send_push_notification_to_group(
            user_ids, title, body, notification_data
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Notifications envoyées au groupe',
            'successCount': response['successCount'],
            'failureCount': response['failureCount'],
            'totalTokens': response.get('totalTokens', 0),
            'invalidUsers': response.get('invalidUsers'),
        })
    except Exception as error:
        logger.error(f"Erreur: {error}")
        return JsonResponse({
            'error': 'Erreur lors de l\'envoi des notifications',
            'details': str(error),
        }, status=500)

