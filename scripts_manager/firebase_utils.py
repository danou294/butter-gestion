"""
Utilitaires pour gérer Firebase avec support des environnements dev/prod
"""
import os
from pathlib import Path


def get_firebase_env_from_session(request=None):
    """
    Récupère l'environnement Firebase depuis la session Django ou la variable d'environnement
    
    Args:
        request: Objet request Django (optionnel)
    
    Returns:
        str: 'dev' ou 'prod'
    """
    # Si on a accès à la requête, vérifier la session
    if request and hasattr(request, 'session'):
        session_env = request.session.get('firebase_env', None)
        if session_env and session_env in ['dev', 'prod']:
            return session_env
    
    # Sinon, utiliser la variable d'environnement
    env = os.getenv('FIREBASE_ENV', 'prod').lower()
    if env not in ['dev', 'prod']:
        env = 'prod'
    
    return env


def get_service_account_path(request=None):
    """
    Récupère le chemin du fichier service account selon l'environnement actif
    
    Args:
        request: Objet request Django (optionnel)
    
    Returns:
        str: Chemin vers le fichier service account
    """
    env = get_firebase_env_from_session(request)
    
    # Calculer le chemin depuis la base du projet
    BASE_DIR = Path(__file__).resolve().parent.parent
    FIREBASE_CREDENTIALS_DIR = BASE_DIR / "firebase_credentials"
    
    if env == 'dev':
        return str(FIREBASE_CREDENTIALS_DIR / "serviceAccountKey.dev.json")
    else:
        return str(FIREBASE_CREDENTIALS_DIR / "serviceAccountKey.prod.json")
