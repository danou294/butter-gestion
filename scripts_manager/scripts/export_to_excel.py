#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script unifié d'export vers Excel
Permet d'exporter :
- Collections Firestore (users, restaurants, recommandations, feedbacks, etc.)
- Utilisateurs Firebase Auth

Usage:
  python scripts/export_to_excel.py                    # Menu interactif
  python scripts/export_to_excel.py --type firestore --collection users
  python scripts/export_to_excel.py --type auth
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials, auth

# Ajouter le répertoire parent au path pour importer config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SERVICE_ACCOUNT_PATH, EXPORTS_DIR


def setup_logging() -> logging.Logger:
    """Configure le système de logging"""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(EXPORTS_DIR / 'export_to_excel.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande"""
    parser = argparse.ArgumentParser(
        description='Export unifié vers Excel (Firestore ou Firebase Auth)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Menu interactif
  python scripts/export_to_excel.py

  # Export d'une collection Firestore
  python scripts/export_to_excel.py --type firestore --collection users

  # Export des utilisateurs Firebase Auth
  python scripts/export_to_excel.py --type auth
        """
    )
    parser.add_argument(
        '--type', '-t',
        choices=['firestore', 'auth'],
        help="Type d'export : 'firestore' pour une collection, 'auth' pour Firebase Auth"
    )
    parser.add_argument(
        '--collection', '-c',
        help="Nom de la collection Firestore (ex: users, restaurants, recommandations, feedbacks)"
    )
    return parser.parse_args()


def ensure_credentials(logger: logging.Logger) -> None:
    """Vérifie et configure les credentials Firebase"""
    creds_path = SERVICE_ACCOUNT_PATH
    if not Path(creds_path).exists():
        raise FileNotFoundError(
            f"Fichier des identifiants non trouvé : {creds_path}\n"
            f"💡 Vérifiez que le fichier existe dans {creds_path}"
        )
    
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
    
    logger.info(f"Identifiants: {creds_path}")


def flatten(value: Any, parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """Aplatit récursivement les dictionnaires; les listes sont sérialisées en JSON."""
    items: Dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            items.update(flatten(v, new_key, sep=sep))
    elif isinstance(value, list):
        # On garde la liste intacte mais on la stocke en JSON pour Excel
        items[parent_key] = json.dumps(value, ensure_ascii=False)
    else:
        # Normalise les datetimes tz-aware -> UTC naïf (compatible Excel)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
        items[parent_key] = value
    return items


def export_firestore_collection(collection_name: str, logger: logging.Logger) -> Path:
    """Exporte une collection Firestore vers Excel"""
    logger.info(f"📊 Export de la collection Firestore '{collection_name}'...")
    
    client = firestore.Client()
    collection_ref = client.collection(collection_name)
    docs = list(collection_ref.stream())
    logger.info(f"✅ {len(docs)} documents trouvés")
    
    records: List[Dict[str, Any]] = []
    for i, doc in enumerate(docs, 1):
        data = doc.to_dict() or {}
        # Ajoute l'identifiant du document
        data_with_id = {**data, 'id': doc.id}
        flat = flatten(data_with_id)
        records.append(flat)
        if i % 100 == 0:
            logger.info(f"  Progression: {i}/{len(docs)}")
    
    # Création du DataFrame
    if not records:
        df = pd.DataFrame(columns=['id'])
        logger.warning("⚠️  Aucun document trouvé, création d'un Excel vide")
    else:
        df = pd.DataFrame(records)
        # Trie les colonnes: id d'abord, puis alphabétique
        cols = list(df.columns)
        if 'id' in cols:
            cols.remove('id')
            cols = ['id'] + sorted(cols)
            df = df.reindex(columns=cols)
    
    # Génération du nom de fichier
    # Nettoyer le nom de la collection (supprimer espaces et tirets en fin)
    clean_collection_name = collection_name.strip().rstrip('-_')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{clean_collection_name}_export_{timestamp}.xlsx"
    output_path = EXPORTS_DIR / filename
    
    # Export Excel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)
    logger.info(f"✅ Export Excel créé: {output_path}")
    logger.info(f"📈 {len(df)} lignes exportées")
    
    return output_path


def export_firebase_auth(logger: logging.Logger) -> Path:
    """Exporte les utilisateurs Firebase Auth vers Excel"""
    logger.info("📊 Export des utilisateurs Firebase Auth...")
    
    # Initialisation Firebase Admin
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        firebase_admin.initialize_app(cred)
    
    # Récupération des utilisateurs
    users = []
    logger.info("  Récupération des utilisateurs...")
    for user in auth.list_users().iterate_all():
        users.append({
            "uid": user.uid,
            "email": str(getattr(user, "email", "") or "").strip(),
            "displayName": str(getattr(user, "display_name", "") or "").strip(),
            "is_anonymous": len(user.provider_data) == 0,
            "created_at_iso": (
                datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000).isoformat()
                if user.user_metadata and user.user_metadata.creation_timestamp else None
            )
        })
    
    logger.info(f"✅ {len(users)} utilisateurs récupérés")
    
    # Création du DataFrame
    fields = ["uid", "email", "displayName", "is_anonymous", "created_at_iso"]
    df = pd.DataFrame(users, columns=fields)
    
    # Nettoyage des données
    logger.info("  Nettoyage des données...")
    initial_count = len(df)
    
    # Supprimer les doublons d'UID
    df = df.drop_duplicates(subset=["uid"])
    if len(df) < initial_count:
        logger.info(f"  {initial_count - len(df)} doublons supprimés")
    
    # Supprimer les comptes totalement vides (sauf l'uid)
    before_empty = len(df)
    df = df[
        df[["email", "displayName", "created_at_iso"]].apply(lambda row: any(row), axis=1)
    ]
    if len(df) < before_empty:
        logger.info(f"  {before_empty - len(df)} comptes vides supprimés")
    
    # Trier par date de création (plus récent en bas)
    df = df.sort_values("created_at_iso")
    
    # Génération du nom de fichier
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"firebase_auth_users_{timestamp}.xlsx"
    output_path = EXPORTS_DIR / filename
    
    # Export Excel
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)
    logger.info(f"✅ Export Excel créé: {output_path}")
    logger.info(f"📈 {len(df)} utilisateurs exportés (après nettoyage)")
    
    return output_path


def show_interactive_menu() -> tuple[str, Optional[str]]:
    """Affiche un menu interactif pour choisir le type d'export"""
    print("\n" + "="*60)
    print("📊 EXPORT UNIFIÉ VERS EXCEL")
    print("="*60)
    print("\nQuelle collection voulez-vous exporter ?")
    print("\n" + "-"*60)
    
    # Collections prédéfinies
    collections = [
        ("users", "Utilisateurs Firestore"),
        ("restaurants", "Restaurants"),
        ("recommandations", "Recommandations"),
        ("feedbacks", "Feedbacks"),
    ]
    
    # Afficher les collections Firestore
    print("\n📁 Collections Firestore :")
    for i, (col_name, col_desc) in enumerate(collections, 1):
        print(f"  {i}. {col_name} - {col_desc}")
    
    # Option pour une collection personnalisée
    print(f"  {len(collections) + 1}. Autre collection (tapez le nom)")
    
    # Option Firebase Auth
    auth_option = len(collections) + 2
    print(f"\n👤 Utilisateurs Firebase Auth :")
    print(f"  {auth_option}. Utilisateurs Firebase Auth")
    
    # Option quitter
    print(f"\n  {auth_option + 1}. Quitter")
    print("-"*60)
    
    while True:
        try:
            choice = input(f"\nVotre choix (1-{auth_option + 1}): ").strip()
            
            # Quitter
            if choice == str(auth_option + 1) or choice.lower() == "0":
                print("👋 Au revoir !")
                sys.exit(0)
            
            # Firebase Auth
            elif choice == str(auth_option):
                return ("auth", None)
            
            # Collection Firestore prédéfinie
            elif choice.isdigit() and 1 <= int(choice) <= len(collections):
                collection_name = collections[int(choice) - 1][0]
                print(f"\n✅ Collection sélectionnée : {collection_name}")
                return ("firestore", collection_name)
            
            # Collection personnalisée
            elif choice == str(len(collections) + 1):
                collection = input("\n📝 Nom de la collection à exporter: ").strip()
                if not collection:
                    print("❌ Le nom de la collection ne peut pas être vide")
                    continue
                print(f"\n✅ Collection sélectionnée : {collection}")
                return ("firestore", collection)
            
            # Essayer de traiter comme un nom de collection direct
            elif choice:
                # Si l'utilisateur tape directement un nom de collection
                print(f"\n✅ Collection sélectionnée : {choice}")
                return ("firestore", choice)
            
            else:
                print(f"❌ Choix invalide. Veuillez choisir un nombre entre 1 et {auth_option + 1}, ou taper le nom d'une collection.")
        
        except KeyboardInterrupt:
            print("\n\n👋 Au revoir !")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Erreur : {e}")
            continue


def main() -> None:
    """Fonction principale"""
    logger = setup_logging()
    args = parse_args()
    
    try:
        ensure_credentials(logger)
        
        # Déterminer le type d'export
        export_type = args.type
        collection = args.collection
        
        # Si aucun argument, afficher le menu interactif
        if not export_type:
            export_type, collection = show_interactive_menu()
        
        # Validation
        if export_type == "firestore" and not collection:
            logger.error("❌ Le nom de la collection est requis pour l'export Firestore")
            logger.info("💡 Utilisez --collection <nom> ou le menu interactif")
            sys.exit(1)
        
        # Exécution de l'export
        logger.info("🚀 Démarrage de l'export...")
        
        if export_type == "firestore":
            output_path = export_firestore_collection(collection, logger)
        elif export_type == "auth":
            output_path = export_firebase_auth(logger)
        else:
            logger.error(f"❌ Type d'export invalide: {export_type}")
            sys.exit(1)
        
        logger.info("="*60)
        logger.info(f"✅ Export terminé avec succès !")
        logger.info(f"📁 Fichier: {output_path.absolute()}")
        logger.info("="*60)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Export annulé par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

