import os
import sys
import subprocess
import json
import logging
import re
from pathlib import Path
from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import threading
import time

# Ajouter le chemin des scripts
SCRIPTS_DIR = Path(__file__).parent / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).parent))

# Configuration
from config import SERVICE_ACCOUNT_PATH, EXPORTS_DIR, INPUT_DIR

# Logger
logger = logging.getLogger(__name__)

# Stockage des tâches en cours
running_tasks = {}


@login_required
def index(request):
    """Page d'accueil"""
    # Vérifier si le fichier service account existe
    service_account_exists = Path(SERVICE_ACCOUNT_PATH).exists()
    context = {
        'service_account_exists': service_account_exists,
        'service_account_path': SERVICE_ACCOUNT_PATH
    }
    return render(request, 'scripts_manager/index.html', context)


@login_required
def export_index(request):
    """Page d'export"""
    return render(request, 'scripts_manager/export.html')


def convert_local_index(request):
    """Page de conversion d'images locales"""
    return render(request, 'scripts_manager/convert_local.html')


def optimize_firebase_index(request):
    """Page d'optimisation Firebase"""
    return render(request, 'scripts_manager/optimize_firebase.html')


def check_missing_index(request):
    """Page de vérification"""
    return render(request, 'scripts_manager/check_missing.html')


def delete_index(request):
    """Page de suppression"""
    return render(request, 'scripts_manager/delete.html')


@login_required
@require_http_methods(["POST"])
def run_export(request):
    """Exécute un script d'export et retourne le fichier en téléchargement direct"""
    try:
        data = json.loads(request.body)
        export_type = data.get('type')  # 'firestore' ou 'auth'
        collection = data.get('collection', '')
        
        # Préparer la commande
        script_path = SCRIPTS_DIR / 'export_to_excel.py'
        cmd = [sys.executable, str(script_path)]
        
        if export_type == 'firestore':
            cmd.extend(['--type', 'firestore', '--collection', collection])
        elif export_type == 'auth':
            cmd.extend(['--type', 'auth'])
        else:
            return JsonResponse({'error': 'Type invalide'}, status=400)
        
        # Définir les variables d'environnement
        env = os.environ.copy()
        env['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_ACCOUNT_PATH
        env['PYTHONPATH'] = str(SCRIPTS_DIR) + ':' + env.get('PYTHONPATH', '')
        
        # Exécuter le script de manière synchrone
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(SCRIPTS_DIR)
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"Erreur lors de l'export: {stderr}")
            return JsonResponse({'error': f'Erreur lors de l\'export: {stderr}'}, status=500)
        
        # Chercher le fichier Excel le plus récent dans EXPORTS_DIR
        excel_files = list(EXPORTS_DIR.glob('*.xlsx'))
        if not excel_files:
            return JsonResponse({'error': 'Aucun fichier Excel généré'}, status=500)
        
        # Trier par date de modification (plus récent en premier)
        excel_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        latest_file = excel_files[0]
        
        # Vérifier que le fichier a été créé récemment (dans les 10 dernières secondes)
        file_age = time.time() - latest_file.stat().st_mtime
        if file_age > 10:
            return JsonResponse({'error': 'Fichier Excel non trouvé ou trop ancien'}, status=500)
        
        # Extraire le nom du fichier réel
        original_filename = latest_file.name
        logger.info(f"Nom de fichier original: {original_filename}")
        
        # Construire le nom de téléchargement de manière très simple et directe
        if export_type == 'firestore':
            # Nettoyer le nom de la collection
            clean_collection = collection.strip()
            # Supprimer tous les underscores et tirets en fin
            while clean_collection.endswith('_') or clean_collection.endswith('-'):
                clean_collection = clean_collection.rstrip('_').rstrip('-')
            # Construire le nom SANS extension d'abord
            base = f"{clean_collection}_export"
            # S'assurer qu'il n'y a pas déjà .xlsx dans le nom
            if base.endswith('.xlsx'):
                base = base[:-5]
            # Supprimer les underscores/tirets en fin
            base = base.rstrip('_').rstrip('-')
            # Ajouter UNIQUEMENT .xlsx à la fin
            download_filename = base + '.xlsx'
        else:
            # Pour Firebase Auth, nom fixe
            download_filename = "firebase_auth_users.xlsx"
        
        # Vérification finale absolue : s'assurer qu'il n'y a qu'un seul .xlsx à la fin
        # Supprimer TOUS les .xlsx du nom
        parts = download_filename.rsplit('.xlsx', 1)
        if len(parts) == 2:
            # Il y avait au moins un .xlsx, on garde la partie avant et on ajoute .xlsx une fois
            base_part = parts[0].rstrip('_').rstrip('-')
            download_filename = base_part + '.xlsx'
        else:
            # Pas de .xlsx trouvé, on en ajoute un
            download_filename = download_filename.rstrip('_').rstrip('-') + '.xlsx'
        
        # Dernière vérification : supprimer tout underscore juste avant .xlsx
        if download_filename.endswith('_.xlsx'):
            download_filename = download_filename[:-6] + '.xlsx'
        
        logger.info(f"Nom de fichier final pour téléchargement: {download_filename}")
        
        # Lire le fichier et le retourner en téléchargement
        file_handle = open(latest_file, 'rb')
        response = HttpResponse(file_handle.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{download_filename}"'
        file_handle.close()
        
        # Supprimer le fichier après le téléchargement
        try:
            latest_file.unlink()
        except Exception as e:
            logger.warning(f"Impossible de supprimer le fichier temporaire: {e}")
        
        return response
    
    except Exception as e:
        logger.error(f"Erreur export: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def run_convert_local(request):
    """Exécute la conversion d'images locales"""
    try:
        data = json.loads(request.body)
        source = data.get('source', 'input/photo-firestore')
        max_width = data.get('max_width', 1920)
        max_height = data.get('max_height', 1920)
        quality = data.get('quality', 85)
        overwrite = data.get('overwrite', False)
        
        # Vérifier que le dossier source existe
        source_path = INPUT_DIR / source.replace('input/', '')
        if not source_path.exists():
            return JsonResponse({'error': f'Dossier source non trouvé: {source_path}'}, status=400)
        
        # Préparer la commande
        script_path = SCRIPTS_DIR / 'convert_local_images.py'
        cmd = [
            sys.executable, str(script_path),
            '--source', str(source_path),
            '--max-width', str(max_width),
            '--max-height', str(max_height),
            '--quality', str(quality)
        ]
        if overwrite:
            cmd.append('--overwrite')
        
        # Exécuter en arrière-plan
        task_id = f"convert_local_{int(time.time())}"
        thread = threading.Thread(
            target=run_script_task,
            args=(task_id, cmd, EXPORTS_DIR)
        )
        thread.start()
        running_tasks[task_id] = {'status': 'running', 'output': []}
        
        return JsonResponse({'task_id': task_id, 'status': 'started'})
    
    except Exception as e:
        logger.error(f"Erreur conversion locale: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def run_optimize_firebase(request):
    """Exécute l'optimisation Firebase"""
    try:
        data = json.loads(request.body)
        operation = data.get('operation')  # 'convert_png' ou 'optimize_existing'
        all_png = data.get('all_png', False)
        remaining = data.get('remaining', False)
        delete_png = data.get('delete_png', False)
        max_width = data.get('max_width', 1920)
        max_height = data.get('max_height', 1920)
        quality = data.get('quality', 85)
        
        # Préparer la commande
        script_path = SCRIPTS_DIR / 'optimize_firebase_images.py'
        cmd = [
            sys.executable, str(script_path),
            '--max-width', str(max_width),
            '--max-height', str(max_height),
            '--quality', str(quality)
        ]
        
        if operation == 'convert_png':
            cmd.append('--convert-png')
            if all_png:
                cmd.append('--all')
            elif remaining:
                cmd.append('--remaining')
            if delete_png:
                cmd.append('--delete-png')
        elif operation == 'optimize_existing':
            cmd.append('--optimize-existing')
        else:
            return JsonResponse({'error': 'Opération invalide'}, status=400)
        
        # Exécuter en arrière-plan
        task_id = f"optimize_firebase_{int(time.time())}"
        thread = threading.Thread(
            target=run_script_task,
            args=(task_id, cmd, EXPORTS_DIR)
        )
        thread.start()
        running_tasks[task_id] = {'status': 'running', 'output': []}
        
        return JsonResponse({'task_id': task_id, 'status': 'started'})
    
    except Exception as e:
        logger.error(f"Erreur optimisation Firebase: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def run_check_missing(request):
    """Exécute la vérification des fichiers manquants"""
    try:
        data = json.loads(request.body)
        check_type = data.get('type')  # 'photos' ou 'logos'
        
        # Préparer la commande
        if check_type == 'photos':
            script_path = SCRIPTS_DIR / 'check_missing_photos.py'
        elif check_type == 'logos':
            script_path = SCRIPTS_DIR / 'check_missing_logos.py'
        else:
            return JsonResponse({'error': 'Type invalide'}, status=400)
        
        cmd = [sys.executable, str(script_path)]
        
        # Exécuter en arrière-plan
        task_id = f"check_missing_{check_type}_{int(time.time())}"
        thread = threading.Thread(
            target=run_script_task,
            args=(task_id, cmd, EXPORTS_DIR)
        )
        thread.start()
        running_tasks[task_id] = {'status': 'running', 'output': []}
        
        return JsonResponse({'task_id': task_id, 'status': 'started'})
    
    except Exception as e:
        logger.error(f"Erreur vérification: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def run_delete(request):
    """Exécute une opération de suppression"""
    try:
        data = json.loads(request.body)
        delete_type = data.get('type')  # 'all_png', 'ending_with_1', 'png_from_photos'
        
        # Préparer la commande
        if delete_type == 'all_png':
            script_path = SCRIPTS_DIR / 'delete_all_png_photos.py'
        elif delete_type == 'ending_with_1':
            script_path = SCRIPTS_DIR / 'delete_photos_not_ending_with_1.py'
        elif delete_type == 'png_from_photos':
            script_path = SCRIPTS_DIR / 'delete_png_from_photos.py'
        else:
            return JsonResponse({'error': 'Type invalide'}, status=400)
        
        cmd = [sys.executable, str(script_path)]
        
        # Exécuter en arrière-plan
        task_id = f"delete_{delete_type}_{int(time.time())}"
        thread = threading.Thread(
            target=run_script_task,
            args=(task_id, cmd, EXPORTS_DIR)
        )
        thread.start()
        running_tasks[task_id] = {'status': 'running', 'output': []}
        
        return JsonResponse({'task_id': task_id, 'status': 'started'})
    
    except Exception as e:
        logger.error(f"Erreur suppression: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def run_script_task(task_id, cmd, exports_dir):
    """Exécute un script en arrière-plan et capture la sortie"""
    try:
        # Définir les variables d'environnement
        env = os.environ.copy()
        env['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_ACCOUNT_PATH
        env['PYTHONPATH'] = str(SCRIPTS_DIR) + ':' + env.get('PYTHONPATH', '')
        
        # Exécuter le script
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(SCRIPTS_DIR)
        )
        
        output = []
        for line in process.stdout:
            output.append(line.strip())
            running_tasks[task_id]['output'] = output[-50:]  # Garder les 50 dernières lignes
        
        process.wait()
        
        running_tasks[task_id]['status'] = 'completed' if process.returncode == 0 else 'failed'
        running_tasks[task_id]['returncode'] = process.returncode
        
    except Exception as e:
        running_tasks[task_id]['status'] = 'failed'
        running_tasks[task_id]['error'] = str(e)


def get_task_status(request, task_id):
    """Récupère le statut d'une tâche"""
    if task_id not in running_tasks:
        return JsonResponse({'error': 'Tâche non trouvée'}, status=404)
    
    task = running_tasks[task_id]
    return JsonResponse({
        'status': task['status'],
        'output': task.get('output', []),
        'error': task.get('error', None)
    })


# Fonction d'upload désactivée - le fichier service account est fixe
# @require_http_methods(["POST"])
# def upload_credentials(request):
#     """Upload le fichier serviceAccountKey.json"""
#     return JsonResponse({'error': 'L\'upload de service account est désactivé. Le fichier est fixe.'}, status=403)


def list_exports(request):
    """Liste tous les fichiers d'export disponibles"""
    exports = []
    if EXPORTS_DIR.exists():
        for file in EXPORTS_DIR.iterdir():
            if file.is_file():
                exports.append({
                    'name': file.name,
                    'size': file.stat().st_size,
                    'modified': file.stat().st_mtime,
                    'url': f'/media/exports/{file.name}'
                })
    
    # Trier par date de modification (plus récent en premier)
    exports.sort(key=lambda x: x['modified'], reverse=True)
    
    return JsonResponse({'exports': exports})


def download_file(request, file_path):
    """Télécharge un fichier depuis exports"""
    # Sécuriser le chemin
    safe_path = Path(file_path).name
    file_full_path = EXPORTS_DIR / safe_path
    
    if not file_full_path.exists() or not file_full_path.is_file():
        return HttpResponse('Fichier non trouvé', status=404)
    
    response = FileResponse(
        open(file_full_path, 'rb'),
        content_type='application/octet-stream'
    )
    response['Content-Disposition'] = f'attachment; filename="{safe_path}"'
    return response


@login_required
def import_restaurants_index(request):
    """Page d'index pour l'import batch de restaurants"""
    return render(request, 'scripts_manager/import_restaurants.html')


@login_required
@require_http_methods(["POST"])
def run_import_restaurants(request):
    """Traite l'upload d'un fichier Excel et lance l'import"""
    try:
        if 'excel_file' not in request.FILES:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        excel_file = request.FILES['excel_file']
        sheet_name = request.POST.get('sheet_name', 'Feuil1')
        
        # Vérifier l'extension
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({'error': 'Le fichier doit être un fichier Excel (.xlsx ou .xls)'}, status=400)
        
        # Sauvegarder le fichier temporairement
        file_path = INPUT_DIR / excel_file.name
        with open(file_path, 'wb+') as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)
        
        logger.info(f"📥 Fichier Excel uploadé: {file_path}")
        
        # Importer le module d'import
        from import_restaurants import import_restaurants_from_excel
        
        # Lancer l'import
        result = import_restaurants_from_excel(str(file_path), sheet_name)
        
        # Supprimer le fichier temporaire après import
        if file_path.exists():
            file_path.unlink()
        
        return JsonResponse({
            'success': True,
            'message': f'Import réussi : {result["imported"]} restaurants importés',
            'imported': result['imported'],
            'backup_dir': result['backup_dir'],
            'log_file': result['log_file'],
            'duplicates': result['duplicates'],
            'missing_tag_rows': result['missing_tag_rows']
        })
        
    except FileNotFoundError as e:
        logger.error(f"❌ Erreur: {e}")
        return JsonResponse({'error': f'Fichier non trouvé: {str(e)}'}, status=404)
    except ValueError as e:
        logger.error(f"❌ Erreur de validation: {e}")
        return JsonResponse({'error': f'Erreur de validation: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'import: {e}")
        import traceback
        return JsonResponse({
            'error': f'Erreur lors de l\'import: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)
