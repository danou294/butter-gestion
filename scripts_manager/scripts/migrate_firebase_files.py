#!/usr/bin/env python3
"""
Script pour migrer le fichier serviceAccountKey.json actuel vers le nouveau système dev/prod

Usage:
    python scripts/migrate_firebase_files.py
    
Ce script va:
1. Chercher le fichier serviceAccountKey.json actuel
2. Le renommer en serviceAccountKey.prod.json
3. Créer un fichier vide serviceAccountKey.dev.json (à remplir manuellement)
"""

import os
import shutil
from pathlib import Path

# Chemins
BASE_DIR = Path(__file__).resolve().parent.parent.parent
FIREBASE_CREDENTIALS_DIR = BASE_DIR / 'firebase_credentials'
MEDIA_ROOT = BASE_DIR / 'media'
INPUT_DIR = MEDIA_ROOT / 'input'

# Chercher l'ancien fichier dans plusieurs emplacements possibles
OLD_FILE_LOCATIONS = [
    INPUT_DIR / 'serviceAccountKey.json',
    FIREBASE_CREDENTIALS_DIR / 'serviceAccountKey.json',
    BASE_DIR / 'serviceAccountKey.json',
]

NEW_PROD_FILE = FIREBASE_CREDENTIALS_DIR / 'serviceAccountKey.prod.json'
NEW_DEV_FILE = FIREBASE_CREDENTIALS_DIR / 'serviceAccountKey.dev.json'

def main():
    print("🔄 Migration des fichiers Firebase vers le système dev/prod\n")
    
    # Créer le dossier firebase_credentials s'il n'existe pas
    FIREBASE_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 Dossier créé : {FIREBASE_CREDENTIALS_DIR}\n")
    
    # Chercher l'ancien fichier dans tous les emplacements possibles
    old_file = None
    for location in OLD_FILE_LOCATIONS:
        if location.exists():
            old_file = location
            break
    
    if old_file:
        print(f"✅ Fichier actuel trouvé : {old_file}")
        
        # Vérifier si le fichier prod existe déjà
        if NEW_PROD_FILE.exists():
            response = input(f"⚠️  Le fichier {NEW_PROD_FILE.name} existe déjà. Écraser ? (o/N): ")
            if response.lower() != 'o':
                print("❌ Migration annulée")
                return
            NEW_PROD_FILE.unlink()
        
        # Copier l'ancien fichier vers prod
        shutil.copy2(old_file, NEW_PROD_FILE)
        print(f"✅ Fichier copié vers : {NEW_PROD_FILE}")
        
        # Renommer l'ancien fichier (optionnel, pour garder une copie)
        backup_file = old_file.parent / f'{old_file.name}.backup'
        if backup_file.exists():
            backup_file.unlink()
        old_file.rename(backup_file)
        print(f"✅ Ancien fichier renommé en : {backup_file.name}")
    else:
        print("⚠️  Fichier actuel non trouvé dans les emplacements suivants :")
        for location in OLD_FILE_LOCATIONS:
            print(f"   - {location}")
        print("\n   Si vous avez déjà migré, c'est normal.")
    
    # Créer le fichier dev vide (placeholder)
    if not NEW_DEV_FILE.exists():
        NEW_DEV_FILE.write_text('{\n    "type": "service_account",\n    "project_id": "VOTRE_PROJET_DEV",\n    "private_key_id": "À_REMPLIR",\n    "private_key": "À_REMPLIR",\n    "client_email": "À_REMPLIR",\n    "client_id": "À_REMPLIR",\n    "auth_uri": "https://accounts.google.com/o/oauth2/auth",\n    "token_uri": "https://oauth2.googleapis.com/token",\n    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",\n    "client_x509_cert_url": "À_REMPLIR"\n}\n')
        print(f"✅ Fichier DEV créé (placeholder) : {NEW_DEV_FILE}")
        print("   ⚠️  IMPORTANT : Remplacez ce fichier par votre vrai fichier serviceAccountKey.json de DEV")
    else:
        print(f"✅ Fichier DEV existe déjà : {NEW_DEV_FILE}")
    
    print("\n✅ Migration terminée !")
    print("\n📝 Prochaines étapes :")
    print("   1. Remplacez le fichier serviceAccountKey.dev.json par votre vrai fichier de DEV")
    print("   2. Définissez FIREBASE_ENV=dev ou FIREBASE_ENV=prod pour basculer entre les environnements")
    print("   3. Par défaut, l'environnement PROD sera utilisé")

if __name__ == '__main__':
    main()
