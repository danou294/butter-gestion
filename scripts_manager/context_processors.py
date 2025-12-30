"""
Context processors pour injecter des variables dans tous les templates
"""
import os
from pathlib import Path

def firebase_env(request):
    """Injecte l'environnement Firebase actif dans tous les templates"""
    # Vérifier d'abord la session Django, puis la variable d'environnement
    session_env = request.session.get('firebase_env', None)
    if session_env and session_env in ['dev', 'prod']:
        firebase_env_active = session_env
    else:
        firebase_env_active = os.getenv('FIREBASE_ENV', 'prod').lower()
        if firebase_env_active not in ['dev', 'prod']:
            firebase_env_active = 'prod'
    
    # Déterminer le label et le chemin
    if firebase_env_active == 'dev':
        firebase_env_label = "🔧 DEV"
        # Calculer le chemin depuis la base du projet
        BASE_DIR = Path(__file__).resolve().parent.parent
        service_account_path = str(BASE_DIR / "firebase_credentials" / "serviceAccountKey.dev.json")
    else:
        firebase_env_label = "🚀 PROD"
        BASE_DIR = Path(__file__).resolve().parent.parent
        service_account_path = str(BASE_DIR / "firebase_credentials" / "serviceAccountKey.prod.json")
    
    return {
        'firebase_env': firebase_env_active,
        'firebase_env_label': firebase_env_label,
        'service_account_path': service_account_path,
    }
