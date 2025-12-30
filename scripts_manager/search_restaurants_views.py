#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vues pour la recherche de restaurants via Google Places API
"""

import os
import sys
import json
import time
import math
import re
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

import pandas as pd
from django.shortcuts import render
from django.http import JsonResponse, FileResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.conf import settings

# Configuration
from config import INPUT_DIR, EXPORTS_DIR
from .firebase_utils import get_service_account_path

logger = logging.getLogger(__name__)

# Chemin vers le script de recherche
SCRIPTS_DIR = Path(__file__).parent / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).parent))


@login_required
def search_restaurants_index(request):
    """Page principale de recherche de restaurants"""
    from .context_processors import firebase_env
    env_context = firebase_env(request)
    
    return render(request, 'scripts_manager/search.html', {
        'firebase_env': env_context['firebase_env'],
        'firebase_env_label': env_context['firebase_env_label'],
    })


@login_required
@require_http_methods(["POST"])
def analyze_excel_columns(request):
    """Analyse un fichier Excel et retourne la liste des colonnes disponibles"""
    try:
        if 'excel_file' not in request.FILES:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        excel_file = request.FILES['excel_file']
        
        # Vérifier l'extension
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({'error': 'Le fichier doit être un fichier Excel (.xlsx ou .xls)'}, status=400)
        
        # Sauvegarder le fichier temporairement
        file_path = INPUT_DIR / excel_file.name
        with open(file_path, 'wb+') as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)
        
        try:
            df = pd.read_excel(file_path, engine='openpyxl', nrows=0)  # Lire seulement les en-têtes
            columns = df.columns.tolist()
            
            # Supprimer le fichier temporaire
            if file_path.exists():
                file_path.unlink()
            
            return JsonResponse({
                'success': True,
                'columns': columns,
                'column_count': len(columns)
            })
        except Exception as e:
            # Supprimer le fichier temporaire en cas d'erreur
            if file_path.exists():
                file_path.unlink()
            logger.error(f"Erreur lors de l'analyse des colonnes: {e}")
            return JsonResponse({'error': f'Erreur lors de l\'analyse: {str(e)}'}, status=500)
            
    except Exception as e:
        logger.error(f"Erreur analyze_excel_columns: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def run_search_restaurants(request):
    """Lance la recherche de restaurants en arrière-plan"""
    try:
        if 'excel_file' not in request.FILES:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        excel_file = request.FILES['excel_file']
        name_column = request.POST.get('name_column', '')
        
        if not name_column:
            return JsonResponse({'error': 'Veuillez sélectionner une colonne pour les noms'}, status=400)
        
        # Vérifier l'extension
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({'error': 'Le fichier doit être un fichier Excel (.xlsx ou .xls)'}, status=400)
        
        # Sauvegarder le fichier temporairement
        file_path = INPUT_DIR / excel_file.name
        with open(file_path, 'wb+') as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)
        
        # Créer le chemin du log avant la recherche
        from datetime import datetime
        from config import BACKUP_DIR, FIRESTORE_COLLECTION
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent
        
        ts_dir = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_base = Path(BACKUP_DIR) if isinstance(BACKUP_DIR, str) else BACKUP_DIR
        search_dir = backup_base / f"search_{ts_dir}"
        search_dir.mkdir(parents=True, exist_ok=True)
        log_file = search_dir / "search_run.log"
        
        # Créer le fichier de log vide pour qu'il soit disponible immédiatement
        log_file.write_text("🔍 Démarrage de la recherche de restaurants...\n", encoding='utf-8')
        
        # Lancer la recherche en arrière-plan
        import_result = {'done': False, 'result': None, 'error': None}
        
        def run_search():
            # Écrire immédiatement dans le log pour confirmer que le thread démarre
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n🚀 Thread de recherche démarré\n")
                    f.write(f"📁 Fichier Excel: {file_path}\n")
                    f.write(f"📋 Colonne: {name_column}\n")
            except Exception as log_init_error:
                logger.error(f"Erreur écriture log initial: {log_init_error}")
            
            try:
                # Importer le module
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"📦 Import du module search_restaurants_script...\n")
                
                from .search_restaurants_script import search_restaurants_from_excel
                
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"✅ Module importé avec succès\n")
                    f.write(f"🔧 Appel de search_restaurants_from_excel...\n")
                
                result = search_restaurants_from_excel(
                    str(file_path), 
                    name_column, 
                    request=request,
                    log_file_path=str(log_file),
                    output_dir=str(search_dir)
                )
                
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"✅ Recherche terminée avec succès\n")
                
                import_result['result'] = result
                import_result['done'] = True
            except ImportError as e:
                import traceback
                error_msg = f"Erreur d'import: {str(e)}"
                error_traceback = traceback.format_exc()
                import_result['error'] = error_msg
                import_result['traceback'] = error_traceback
                import_result['done'] = True
                
                # Écrire l'erreur dans le fichier de log
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n❌ ERREUR D'IMPORT:\n")
                        f.write(f"{error_msg}\n")
                        f.write(f"\n📋 Traceback:\n{error_traceback}\n")
                        f.write(f"\n💡 Vérifiez que le module search_restaurants_script existe et est importable\n")
                except Exception as log_error:
                    logger.error(f"Impossible d'écrire l'erreur dans le log: {log_error}")
            except Exception as e:
                import traceback
                error_msg = str(e)
                error_traceback = traceback.format_exc()
                import_result['error'] = error_msg
                import_result['traceback'] = error_traceback
                import_result['done'] = True
                
                # Écrire l'erreur dans le fichier de log pour que l'utilisateur la voie
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n❌ ERREUR lors de la recherche:\n")
                        f.write(f"{error_msg}\n")
                        f.write(f"\n📋 Traceback:\n{error_traceback}\n")
                except Exception as log_error:
                    logger.error(f"Impossible d'écrire l'erreur dans le log: {log_error}")
            finally:
                # Supprimer le fichier temporaire après recherche
                if file_path.exists():
                    try:
                        file_path.unlink()
                        with open(log_file, 'a', encoding='utf-8') as f:
                            f.write(f"🗑️  Fichier temporaire supprimé\n")
                    except Exception as cleanup_error:
                        logger.error(f"Erreur lors du nettoyage: {cleanup_error}")
        
        thread = threading.Thread(target=run_search)
        thread.daemon = True
        thread.start()
        
        # Retourner immédiatement le chemin du log pour permettre le polling
        log_file_relative = str(log_file.relative_to(BASE_DIR)) if str(log_file).startswith(str(BASE_DIR)) else str(log_file)
        
        return JsonResponse({
            'success': True,
            'message': 'Recherche démarrée',
            'log_file': log_file_relative,
            'status': 'running'
        })
        
    except Exception as e:
        logger.error(f"Erreur run_search_restaurants: {e}")
        import traceback
        return JsonResponse({
            'error': f'Erreur: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_search_logs(request):
    """Récupère les logs de recherche en temps réel"""
    try:
        log_file = request.GET.get('log_file')
        if not log_file:
            return JsonResponse({'error': 'Paramètre log_file manquant'}, status=400)
        
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent
        
        # Construire le chemin complet
        if not log_file.startswith('/'):
            # Chemin relatif depuis BASE_DIR
            log_path = BASE_DIR / log_file
        else:
            # Chemin absolu
            log_path = Path(log_file)
        
        if not log_path.exists():
            return JsonResponse({'error': 'Fichier de log non trouvé'}, status=404)
        
        # Lire le fichier de log
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                logs = f.read()
            
            # Vérifier si la recherche est terminée et récupérer le fichier résultat
            result_file = None
            is_complete = False
            if '✅ Recherche terminée' in logs or '🎉 Fin de recherche' in logs or 'Fichier de résultat:' in logs:
                is_complete = True
                # Chercher le fichier Excel dans le même répertoire que le log
                log_dir = log_path.parent
                excel_files = list(log_dir.glob('*.xlsx'))
                if excel_files:
                    # Prendre le fichier le plus récent
                    excel_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                    result_file = str(excel_files[0].relative_to(BASE_DIR)) if str(excel_files[0]).startswith(str(BASE_DIR)) else str(excel_files[0])
            
            return JsonResponse({
                'success': True,
                'logs': logs,
                'file': str(log_path),
                'complete': is_complete,
                'result_file': result_file
            })
        except Exception as e:
            logger.error(f"Erreur lors de la lecture du log: {e}")
            return JsonResponse({'error': f'Erreur lors de la lecture: {str(e)}'}, status=500)
            
    except Exception as e:
        logger.error(f"Erreur get_search_logs: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def download_search_result(request):
    """Télécharge le fichier Excel de résultat de recherche"""
    try:
        file_path = request.GET.get('file')
        if not file_path:
            return JsonResponse({'error': 'Paramètre file manquant'}, status=400)
        
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent
        
        # Construire le chemin complet
        if not file_path.startswith('/'):
            # Chemin relatif depuis BASE_DIR
            full_path = BASE_DIR / file_path
        else:
            # Chemin absolu
            full_path = Path(file_path)
        
        if not full_path.exists():
            return JsonResponse({'error': 'Fichier non trouvé'}, status=404)
        
        # Vérifier que c'est un fichier Excel
        if not full_path.suffix == '.xlsx':
            return JsonResponse({'error': 'Fichier invalide'}, status=400)
        
        # Lire le fichier et le retourner en téléchargement
        file_handle = open(full_path, 'rb')
        response = HttpResponse(file_handle.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{full_path.name}"'
        file_handle.close()
        
        return response
        
    except Exception as e:
        logger.error(f"Erreur download_search_result: {e}")
        return JsonResponse({'error': str(e)}, status=500)

