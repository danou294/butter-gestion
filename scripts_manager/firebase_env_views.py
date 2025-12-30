"""
Vues pour gérer le changement d'environnement Firebase
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import logging

logger = logging.getLogger(__name__)


@login_required
def switch_firebase_env(request):
    """
    Change l'environnement Firebase (dev/prod) via la session Django
    """
    if request.method == 'POST':
        env = request.POST.get('env', '').lower()
        
        if env not in ['dev', 'prod']:
            messages.error(request, "Environnement invalide. Utilisez 'dev' ou 'prod'.")
            return redirect(request.META.get('HTTP_REFERER', '/'))
        
        # Sauvegarder dans la session
        request.session['firebase_env'] = env
        request.session.save()
        
        # Vider les caches Firebase pour forcer le rechargement avec le nouvel environnement
        from django.core.cache import cache
        import scripts_manager.users_views as uv
        
        # Réinitialiser l'app Firebase globale si elle existe
        if uv.FIREBASE_APP:
            try:
                import firebase_admin
                firebase_admin.delete_app(uv.FIREBASE_APP)
            except Exception as e:
                logger.warning(f"Erreur lors de la suppression de l'app Firebase: {e}")
            # Réinitialiser les variables globales
            uv.FIREBASE_APP = None
            uv.FIREBASE_APP_ENV = None
        
        # Vider TOUS les caches liés à Firebase (dev et prod)
        cache_patterns = [
            'firestore_users_cache_',
            'firebase_auth_users_cache_',
            'fcm_tokens_cache_',
            'merged_users_cache_',
            'restaurants_collection_cache_',
            'photos_cache_',
        ]
        for pattern in cache_patterns:
            # Vider les caches pour dev et prod
            cache.delete(f'{pattern}dev')
            cache.delete(f'{pattern}prod')
            # Vider aussi les anciennes clés sans suffixe
            cache.delete(pattern)
        
        # Forcer la réinitialisation de l'app Firebase au prochain appel
        # En mettant FIREBASE_APP_ENV à None, on force get_firebase_app() à réinitialiser
        uv.FIREBASE_APP_ENV = None
        
        logger.info(f"🔄 Environnement Firebase changé vers: {env} (utilisateur: {request.user.username})")
        
        messages.success(request, f"✅ Environnement Firebase changé vers: {env.upper()}")
        
        # Rediriger vers la page précédente ou l'accueil
        redirect_url = request.META.get('HTTP_REFERER', '/')
        return redirect(redirect_url)
    
    return redirect('scripts_manager:index')


@login_required
def get_firebase_env(request):
    """
    API pour obtenir l'environnement Firebase actuel
    """
    import os
    from pathlib import Path
    
    # Vérifier d'abord la session, puis la variable d'environnement
    session_env = request.session.get('firebase_env', None)
    if session_env and session_env in ['dev', 'prod']:
        env = session_env
    else:
        env = os.getenv('FIREBASE_ENV', 'prod').lower()
        if env not in ['dev', 'prod']:
            env = 'prod'
    
    # Vérifier si le fichier existe
    BASE_DIR = Path(__file__).resolve().parent.parent
    if env == 'dev':
        file_path = BASE_DIR / "firebase_credentials" / "serviceAccountKey.dev.json"
        label = "🔧 DEV"
    else:
        file_path = BASE_DIR / "firebase_credentials" / "serviceAccountKey.prod.json"
        label = "🚀 PROD"
    
    file_exists = file_path.exists()
    
    return JsonResponse({
        'env': env,
        'label': label,
        'file_exists': file_exists,
        'file_path': str(file_path),
    })
