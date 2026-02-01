import os
import sys
import subprocess
import json
import logging
import re
import base64
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
from config import EXPORTS_DIR, INPUT_DIR, SERVICE_ACCOUNT_PATH_DEV, SERVICE_ACCOUNT_PATH_PROD
from .firebase_utils import get_service_account_path

# Logger
logger = logging.getLogger(__name__)

# Stockage des tâches en cours
running_tasks = {}


def serve_daniel_image(request):
    """Sert l'image de la page troll : IMG_5849.HEIC (converti en JPEG) ou daniel.jpg."""
    import io
    heic_paths = [
        Path(settings.BASE_DIR) / 'scripts_manager' / 'static' / 'scripts_manager' / 'IMG_5849.HEIC',
        Path(settings.BASE_DIR) / 'IMG_5849.HEIC',
    ]
    for path in heic_paths:
        if path.exists():
            try:
                import pillow_heif
                from PIL import Image
                pillow_heif.register_heif_opener()
                img = Image.open(path)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=90)
                buf.seek(0)
                response = HttpResponse(buf.getvalue(), content_type='image/jpeg')
                response['Cache-Control'] = 'public, max-age=86400'
                return response
            except (ImportError, Exception):
                continue
    for path in [
        Path(settings.BASE_DIR) / 'scripts_manager' / 'static' / 'scripts_manager' / 'daniel.jpg',
        Path(settings.BASE_DIR) / 'daniel.jpg',
    ]:
        if path.exists():
            response = FileResponse(open(path, 'rb'), content_type='image/jpeg')
            response['Cache-Control'] = 'public, max-age=86400'
            return response
    return HttpResponse(status=404)


def _get_daniel_image_base64():
    """Lit daniel.jpg et retourne son contenu en base64, ou None si absent."""
    for path in [
        Path(settings.BASE_DIR) / 'scripts_manager' / 'static' / 'scripts_manager' / 'daniel.jpg',
        Path(settings.BASE_DIR) / 'daniel.jpg',
    ]:
        if path.exists():
            try:
                with open(path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('ascii')
            except Exception:
                continue
    return None


@login_required
def augmenter_daniel(request):
    """Page troll : combien tu veux augmenter Daniel ?"""
    # URL absolue pour l'image (évite les data URL trop longues)
    from django.urls import reverse
    daniel_url = request.build_absolute_uri(reverse('scripts_manager:serve_daniel_image'))
    context = {'daniel_image_url': daniel_url}
    return render(request, 'scripts_manager/augmenter_daniel.html', context)


@login_required
def index(request):
    """Page d'accueil"""
    # Récupérer le chemin selon l'environnement actif (depuis la session)
    service_account_path = get_service_account_path(request)
    service_account_exists = Path(service_account_path).exists()
    service_account_dev_exists = Path(SERVICE_ACCOUNT_PATH_DEV).exists()
    service_account_prod_exists = Path(SERVICE_ACCOUNT_PATH_PROD).exists()
    
    # Récupérer l'environnement depuis le context processor
    from .context_processors import firebase_env
    env_context = firebase_env(request)
    
    context = {
        'service_account_exists': service_account_exists,
        'service_account_path': service_account_path,
        'firebase_env': env_context['firebase_env'],
        'firebase_env_label': env_context['firebase_env_label'],
        'service_account_dev_exists': service_account_dev_exists,
        'service_account_prod_exists': service_account_prod_exists,
        'service_account_dev_path': SERVICE_ACCOUNT_PATH_DEV,
        'service_account_prod_path': SERVICE_ACCOUNT_PATH_PROD,
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
        service_account_path = get_service_account_path(request)
        env['GOOGLE_APPLICATION_CREDENTIALS'] = service_account_path
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
        service_account_path = get_service_account_path(request)
        env['GOOGLE_APPLICATION_CREDENTIALS'] = service_account_path
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
    # Récupérer l'environnement actif pour le passer au template
    from .context_processors import firebase_env
    env_context = firebase_env(request)
    
    # Récupérer la liste des GIFs/memes disponibles
    import os
    import json
    from pathlib import Path
    loading_gifs_dir = Path(__file__).resolve().parent / 'static' / 'loading_gifs'
    loading_gifs = []
    
    if loading_gifs_dir.exists():
        allowed_extensions = ['.gif', '.png', '.jpg', '.jpeg']
        for file in loading_gifs_dir.iterdir():
            if file.is_file() and file.suffix.lower() in allowed_extensions:
                loading_gifs.append(file.name)
    
    return render(request, 'scripts_manager/import_restaurants.html', {
        'firebase_env': env_context['firebase_env'],
        'firebase_env_label': env_context['firebase_env_label'],
        'loading_gifs': json.dumps(loading_gifs),  # Convertir en JSON pour JavaScript
    })


@login_required
def restore_backup_index(request):
    """Page d'index pour restaurer un backup"""
    return render(request, 'scripts_manager/restore_backup.html')


@login_required
@require_http_methods(["POST"])
def run_import_restaurants(request):
    """Traite l'upload d'un fichier Excel et lance l'import - Fonctionne en DEV et PROD"""
    try:
        # Détecter l'environnement Firebase (dev ou prod)
        from .firebase_utils import get_firebase_env_from_session
        current_env = get_firebase_env_from_session(request)
        
        logger.info(f"📥 Import de restaurants - Environnement: {current_env.upper()}")
        
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
        
        logger.info(f"📥 Fichier Excel uploadé: {file_path} (env: {current_env})")
        
        # Créer le chemin du log avant l'import pour pouvoir le retourner immédiatement
        from datetime import datetime
        from config import BACKUP_DIR, FIRESTORE_COLLECTION
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent
        
        ts_dir = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        # Convertir BACKUP_DIR en Path si c'est une chaîne
        backup_base = Path(BACKUP_DIR) if isinstance(BACKUP_DIR, str) else BACKUP_DIR
        backup_dir = backup_base / f"{FIRESTORE_COLLECTION}_{ts_dir}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        log_file = backup_dir / "import_run.log"
        
        # Créer le fichier de log vide pour qu'il soit disponible immédiatement
        log_file.write_text("🚀 Démarrage import end-to-end\n", encoding='utf-8')
        
        # Lancer l'import en arrière-plan pour permettre le polling des logs
        import threading
        import_result = {'done': False, 'result': None, 'error': None}
        
        def run_import():
            try:
                from import_restaurants import import_restaurants_from_excel
                result = import_restaurants_from_excel(str(file_path), sheet_name, request=request, log_file_path=str(log_file))
                import_result['result'] = result
                import_result['done'] = True
            except Exception as e:
                import traceback
                import_result['error'] = str(e)
                import_result['traceback'] = traceback.format_exc()
                import_result['done'] = True
            finally:
                # Supprimer le fichier temporaire après import
                if file_path.exists():
                    file_path.unlink()
        
        thread = threading.Thread(target=run_import)
        thread.daemon = True
        thread.start()
        
        # Retourner immédiatement le chemin du log pour permettre le polling
        log_file_relative = str(log_file.relative_to(BASE_DIR)) if str(log_file).startswith(str(BASE_DIR)) else str(log_file)
        
        return JsonResponse({
            'success': True,
            'message': 'Import démarré',
            'log_file': log_file_relative,
            'status': 'running'
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


@login_required
@require_http_methods(["POST"])
def dev_import_function(request):
    """Fonctions supplémentaires pour l'import en mode DEV uniquement"""
    try:
        # Vérifier que nous sommes en DEV
        from .firebase_utils import get_firebase_env_from_session
        current_env = get_firebase_env_from_session(request)
        
        if current_env != 'dev':
            return JsonResponse({
                'error': 'Cette fonction est disponible uniquement en mode DEV'
            }, status=403)
        
        action = request.POST.get('action')
        
        if action == 'analyze':
            # Analyser le fichier Excel
            if 'excel_file' not in request.FILES:
                return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
            
            excel_file = request.FILES['excel_file']
            file_path = INPUT_DIR / excel_file.name
            with open(file_path, 'wb+') as destination:
                for chunk in excel_file.chunks():
                    destination.write(chunk)
            
            try:
                import pandas as pd
                xls = pd.ExcelFile(file_path)
                
                result = {
                    'sheets': xls.sheet_names,
                    'file_size': file_path.stat().st_size,
                    'file_name': excel_file.name
                }
                
                # Analyser la première feuille
                if xls.sheet_names:
                    df = pd.read_excel(file_path, sheet_name=xls.sheet_names[0], nrows=0)
                    result['columns'] = df.columns.tolist()
                    result['column_count'] = len(df.columns)
                
                if file_path.exists():
                    file_path.unlink()
                
                return JsonResponse({'success': True, 'result': result})
            except Exception as e:
                if file_path.exists():
                    file_path.unlink()
                return JsonResponse({'error': f'Erreur lors de l\'analyse: {str(e)}'}, status=500)
        
        elif action == 'preview':
            # Prévisualiser les données
            if 'excel_file' not in request.FILES:
                return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
            
            excel_file = request.FILES['excel_file']
            sheet_name = request.POST.get('sheet_name', 'Feuil1')
            file_path = INPUT_DIR / excel_file.name
            with open(file_path, 'wb+') as destination:
                for chunk in excel_file.chunks():
                    destination.write(chunk)
            
            try:
                import pandas as pd
                df = pd.read_excel(file_path, sheet_name=sheet_name, nrows=10)
                
                preview = df.to_dict('records')
                total = len(pd.read_excel(file_path, sheet_name=sheet_name))
                
                if file_path.exists():
                    file_path.unlink()
                
                return JsonResponse({
                    'success': True,
                    'preview': preview,
                    'total': total
                })
            except Exception as e:
                if file_path.exists():
                    file_path.unlink()
                return JsonResponse({'error': f'Erreur lors de la prévisualisation: {str(e)}'}, status=500)
        
        elif action == 'test_import':
            # Test d'import partiel (limité)
            limit = int(request.POST.get('limit', 5))
            if 'excel_file' not in request.FILES:
                return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
            
            excel_file = request.FILES['excel_file']
            sheet_name = request.POST.get('sheet_name', 'Feuil1')
            file_path = INPUT_DIR / excel_file.name
            with open(file_path, 'wb+') as destination:
                for chunk in excel_file.chunks():
                    destination.write(chunk)
            
            try:
                from import_restaurants import convert_excel, import_records, init_firestore
                import os
                from datetime import datetime
                
                db = init_firestore("", request)
                backup_dir = os.path.join(EXPORTS_DIR, "test_import_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
                os.makedirs(backup_dir, exist_ok=True)
                log_file = os.path.join(backup_dir, "test_import.log")
                
                out_json = os.path.join(backup_dir, "test_restaurants.json")
                out_ndjson = os.path.join(backup_dir, "test_restaurants.ndjson")
                out_csv = os.path.join(backup_dir, "test_restaurants.csv")
                
                records, conv_report = convert_excel(str(file_path), sheet_name, out_json, out_ndjson, out_csv, log_file)
                
                # Limiter à N enregistrements
                test_records = records[:limit]
                imported = import_records(db, "restaurants", test_records, 400, log_file)
                
                if file_path.exists():
                    file_path.unlink()
                
                return JsonResponse({
                    'success': True,
                    'imported': imported,
                    'result': {
                        'total_converted': len(records),
                        'test_imported': imported,
                        'backup_dir': backup_dir
                    }
                })
            except Exception as e:
                if file_path.exists():
                    file_path.unlink()
                logger.error(f"❌ Erreur test import: {e}")
                return JsonResponse({'error': f'Erreur lors du test: {str(e)}'}, status=500)
        
        elif action == 'validate':
            # Valider les données
            if 'excel_file' not in request.FILES:
                return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
            
            excel_file = request.FILES['excel_file']
            sheet_name = request.POST.get('sheet_name', 'Feuil1')
            file_path = INPUT_DIR / excel_file.name
            with open(file_path, 'wb+') as destination:
                for chunk in excel_file.chunks():
                    destination.write(chunk)
            
            try:
                import pandas as pd
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                
                total = len(df)
                valid = 0
                errors = []
                
                # Vérifier les colonnes requises
                required_columns = ['Ref', 'Nom de base', 'Vrai Nom']
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    errors.append(f"Colonnes manquantes: {', '.join(missing_columns)}")
                
                # Valider chaque ligne
                for idx, row in df.iterrows():
                    if pd.notna(row.get('Ref')) and pd.notna(row.get('Nom de base')):
                        valid += 1
                    else:
                        errors.append(f"Ligne {idx + 2}: Ref ou Nom de base manquant")
                
                if file_path.exists():
                    file_path.unlink()
                
                return JsonResponse({
                    'success': True,
                    'validation': {
                        'total': total,
                        'valid': valid,
                        'errors': len(errors),
                        'error_details': errors[:20]  # Limiter à 20 erreurs
                    }
                })
            except Exception as e:
                if file_path.exists():
                    file_path.unlink()
                return JsonResponse({'error': f'Erreur lors de la validation: {str(e)}'}, status=500)
        
        else:
            return JsonResponse({'error': 'Action non reconnue'}, status=400)
            
    except Exception as e:
        logger.error(f"❌ Erreur fonction DEV: {e}")
        import traceback
        return JsonResponse({
            'error': f'Erreur: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)


@login_required
@require_http_methods(["POST"])
def analyze_excel_sheets(request):
    """Analyse un fichier Excel et retourne la liste des feuilles disponibles"""
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
            import pandas as pd
            xls = pd.ExcelFile(file_path)
            sheets = xls.sheet_names
            
            # Supprimer le fichier temporaire
            if file_path.exists():
                file_path.unlink()
            
            return JsonResponse({
                'success': True,
                'sheets': sheets,
                'default_sheet': sheets[0] if sheets else 'Feuil1'
            })
        except Exception as e:
            # Supprimer le fichier temporaire en cas d'erreur
            if file_path.exists():
                file_path.unlink()
            logger.error(f"Erreur lors de l'analyse des feuilles: {e}")
            return JsonResponse({'error': f'Erreur lors de l\'analyse: {str(e)}'}, status=500)
            
    except Exception as e:
        logger.error(f"Erreur analyze_excel_sheets: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_import_logs(request):
    """Récupère les logs d'import en temps réel"""
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
            
            return JsonResponse({
                'success': True,
                'logs': logs,
                'file': str(log_path)
            })
        except Exception as e:
            logger.error(f"Erreur lors de la lecture du log: {e}")
            return JsonResponse({'error': f'Erreur lors de la lecture: {str(e)}'}, status=500)
            
    except Exception as e:
        logger.error(f"Erreur get_import_logs: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def list_backups(request):
    """Liste tous les backups disponibles"""
    try:
        from restore_backup import list_available_backups
        backups = list_available_backups()
        return JsonResponse({
            'success': True,
            'backups': backups
        })
    except Exception as e:
        logger.error(f"Erreur lors de la liste des backups: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def restore_backup(request):
    """Restaure un backup de restaurants"""
    try:
        data = json.loads(request.body)
        backup_dir = data.get('backup_dir')
        create_backup_before = data.get('create_backup_before', True)
        
        if not backup_dir:
            return JsonResponse({'error': 'Le chemin du backup est requis'}, status=400)
        
        logger.info(f"🔄 Démarrage de la restauration depuis: {backup_dir}")
        
        from restore_backup import restore_from_backup
        
        # Restaurer le backup
        result = restore_from_backup(backup_dir, create_backup_before=create_backup_before, request=request)
        
        logger.info(f"✅ Restauration terminée: {result['imported']} restaurants restaurés")
        
        return JsonResponse({
            'success': True,
            'message': f'Restauration réussie : {result["imported"]} restaurants restaurés',
            'imported': result['imported'],
            'backup_dir': result['backup_dir'],
            'backup_before_dir': result.get('backup_before_dir'),
            'total_records': result.get('total_records', 0)
        })
        
    except FileNotFoundError as e:
        logger.error(f"❌ Erreur: {e}")
        return JsonResponse({'error': f'Backup non trouvé: {str(e)}'}, status=404)
    except ValueError as e:
        logger.error(f"❌ Erreur de validation: {e}")
        return JsonResponse({'error': f'Erreur de validation: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"❌ Erreur lors de la restauration: {e}")
        import traceback
        return JsonResponse({
            'error': f'Erreur lors de la restauration: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)
