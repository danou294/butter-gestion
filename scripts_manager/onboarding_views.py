"""
Vues pour la gestion des restaurants d'onboarding.
Collection Firestore : onboarding_restaurants
"""
import os
import csv
import io
import json
import logging
import tempfile
from pathlib import Path

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from .firebase_utils import get_firebase_env_from_session
from .import_onboarding import (
    parse_onboarding_excel,
    import_to_firestore,
    get_all_onboarding_restaurants,
    get_onboarding_restaurant,
    delete_onboarding_restaurant,
)

logger = logging.getLogger(__name__)


@login_required
def onboarding_list(request):
    """Liste tous les restaurants d'onboarding."""
    env = get_firebase_env_from_session(request)

    restaurants = get_all_onboarding_restaurants(request)

    # Trier par lieu puis par nom
    lieu_order = {'Coffee shop': 0, 'Bar': 1, 'Restaurant': 2}
    restaurants.sort(key=lambda r: (lieu_order.get(r.get('lieu', ''), 9), r.get('name', '')))

    # Stats
    stats = {
        'total': len(restaurants),
        'coffee_shops': sum(1 for r in restaurants if r.get('lieu') == 'Coffee shop'),
        'bars': sum(1 for r in restaurants if r.get('lieu') == 'Bar'),
        'restaurants': sum(1 for r in restaurants if r.get('lieu') == 'Restaurant'),
        'with_photos': sum(1 for r in restaurants if r.get('image_urls')),
        'with_logos': sum(1 for r in restaurants if r.get('logo_url')),
    }

    # Filtrage par lieu
    filter_lieu = request.GET.get('lieu')
    if filter_lieu:
        restaurants = [r for r in restaurants if r.get('lieu') == filter_lieu]

    context = {
        'restaurants': restaurants,
        'stats': stats,
        'filter_lieu': filter_lieu,
        'env': env,
    }
    return render(request, 'scripts_manager/onboarding/list.html', context)


@login_required
def onboarding_detail(request, restaurant_id):
    """Détail d'un restaurant d'onboarding."""
    restaurant = get_onboarding_restaurant(restaurant_id, request)

    if not restaurant:
        messages.error(request, f"Restaurant onboarding '{restaurant_id}' introuvable.")
        return redirect('scripts_manager:onboarding_list')

    context = {
        'restaurant': restaurant,
        'restaurant_json': json.dumps(restaurant, indent=2, ensure_ascii=False, default=str),
    }
    return render(request, 'scripts_manager/onboarding/detail.html', context)


@login_required
@require_http_methods(["POST"])
def onboarding_delete(request, restaurant_id):
    """Supprime un restaurant d'onboarding."""
    success = delete_onboarding_restaurant(restaurant_id, request)

    if success:
        messages.success(request, f"Restaurant '{restaurant_id}' supprimé.")
    else:
        messages.error(request, f"Erreur lors de la suppression de '{restaurant_id}'.")

    return redirect('scripts_manager:onboarding_list')


@login_required
def onboarding_import(request):
    """Page d'import Excel pour les restaurants d'onboarding."""
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')

        if not excel_file:
            messages.error(request, "Veuillez sélectionner un fichier.")
            return redirect('scripts_manager:onboarding_import')

        if not excel_file.name.endswith(('.xlsx', '.xls', '.csv')):
            messages.error(request, "Le fichier doit être au format Excel (.xlsx, .xls) ou CSV (.csv).")
            return redirect('scripts_manager:onboarding_import')

        # Sauvegarder temporairement avec la bonne extension
        suffix = '.csv' if excel_file.name.endswith('.csv') else '.xlsx'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in excel_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            sheet_name = request.POST.get('sheet_name')
            records, report = parse_onboarding_excel(tmp_path, sheet_name)

            # Stocker en session pour la confirmation
            request.session['onboarding_import_records'] = records
            request.session['onboarding_import_report'] = report

            context = {
                'records': records,
                'report': report,
                'step': 'preview',
            }
            return render(request, 'scripts_manager/onboarding/import.html', context)

        except Exception as e:
            logger.error(f"Erreur parsing Excel onboarding: {e}")
            messages.error(request, f"Erreur lors de l'analyse du fichier: {str(e)}")
            return redirect('scripts_manager:onboarding_import')
        finally:
            os.unlink(tmp_path)

    # GET : afficher le formulaire
    context = {
        'step': 'upload',
    }
    return render(request, 'scripts_manager/onboarding/import.html', context)


@login_required
@require_http_methods(["POST"])
def onboarding_import_confirm(request):
    """Confirme et exécute l'import dans Firestore."""
    records = request.session.get('onboarding_import_records')
    report = request.session.get('onboarding_import_report')

    if not records:
        messages.error(request, "Aucune donnée à importer. Recommencez l'upload.")
        return redirect('scripts_manager:onboarding_import')

    env = get_firebase_env_from_session(request)
    result = import_to_firestore(records, request=request, clear_first=True)

    # Nettoyer la session
    request.session.pop('onboarding_import_records', None)
    request.session.pop('onboarding_import_report', None)

    if result['success']:
        messages.success(
            request,
            f"Import réussi sur {env.upper()} : {result['imported']} restaurants importés "
            f"({result['deleted']} anciens supprimés)."
        )
    else:
        errors_str = ', '.join(result['errors'])
        messages.error(request, f"Erreur lors de l'import: {errors_str}")

    return redirect('scripts_manager:onboarding_list')


@login_required
def onboarding_export(request):
    """Exporte les restaurants d'onboarding en CSV ou Excel."""
    fmt = request.GET.get('format', 'csv')

    restaurants = get_all_onboarding_restaurants(request)

    # Trier par lieu puis par nom
    lieu_order = {'Coffee shop': 0, 'Bar': 1, 'Restaurant': 2}
    restaurants.sort(key=lambda r: (lieu_order.get(r.get('lieu', ''), 9), r.get('name', '')))

    headers = ['Nom du restaurant', 'Tag', 'Lieu', 'Spécialité']
    rows = []
    for r in restaurants:
        rows.append({
            'Nom du restaurant': r.get('name', ''),
            'Tag': r.get('tag', ''),
            'Lieu': r.get('lieu', ''),
            'Spécialité': r.get('specialite', '') or '',
        })

    if fmt == 'xlsx':
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Onboarding'
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h, '') for h in headers])
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="onboarding_restaurants.xlsx"'
        return response
    else:
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="onboarding_restaurants.csv"'
        response.write('\ufeff')
        writer = csv.DictWriter(response, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        return response
