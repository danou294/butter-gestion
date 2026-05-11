"""
Views pour la gestion des "Coups de coeur de la semaine"
Collection Firestore : coups_de_coeur (document 'current')
Structure : { restaurantIds: [...], weekLabel: "...", updatedAt: timestamp }
"""

import csv
import io
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import datetime

from .restaurants_views import get_firestore_client
from .firebase_utils import get_firebase_bucket


@login_required
def coups_de_coeur_manage(request):
    """
    Page de gestion des coups de coeur : affiche la sélection actuelle
    et permet d'ajouter/retirer des restaurants.
    """
    try:
        db = get_firestore_client(request)
        bucket_name = get_firebase_bucket(request)

        # Charger la sélection actuelle
        doc_ref = db.collection('coups_de_coeur').document('current')
        doc = doc_ref.get()

        current_ids = []
        week_label = ''
        updated_at = None

        if doc.exists:
            data = doc.to_dict()
            current_ids = data.get('restaurantIds', [])
            week_label = data.get('weekLabel', '')
            updated_at = data.get('updatedAt')

        # Charger les restaurants sélectionnés avec leurs détails
        selected_restaurants = []
        if current_ids:
            for rid in current_ids:
                rdoc = db.collection('restaurants').document(rid).get()
                if rdoc.exists:
                    rdata = rdoc.to_dict()
                    rdata['id'] = rdoc.id
                    # Générer l'URL du logo
                    logo_ref = rdata.get('logoUrl') or rdata.get('logo', '')
                    if logo_ref and not logo_ref.startswith('http'):
                        path = f"Logos/{logo_ref}.webp"
                        import urllib.parse
                        encoded_path = urllib.parse.quote(path, safe='')
                        rdata['logoFullUrl'] = f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_path}?alt=media"
                    elif logo_ref and logo_ref.startswith('http'):
                        rdata['logoFullUrl'] = logo_ref
                    else:
                        rdata['logoFullUrl'] = ''
                    selected_restaurants.append(rdata)

        # Charger TOUS les restaurants pour le sélecteur
        all_restaurants_docs = db.collection('restaurants').order_by('name').stream()
        all_restaurants = []
        for rdoc in all_restaurants_docs:
            rdata = rdoc.to_dict()
            rdata['id'] = rdoc.id
            all_restaurants.append({
                'id': rdoc.id,
                'name': rdata.get('name', rdoc.id),
                'cuisine': rdata.get('cuisine', ''),
                'arrondissement': rdata.get('arrondissement', ''),
            })

        context = {
            'selected_restaurants': selected_restaurants,
            'current_ids': current_ids,
            'week_label': week_label,
            'updated_at': updated_at,
            'all_restaurants': all_restaurants,
            'selected_count': len(selected_restaurants),
        }

        return render(request, 'scripts_manager/coups_de_coeur/manage.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement des coups de coeur : {str(e)}")
        return render(request, 'scripts_manager/coups_de_coeur/manage.html', {
            'selected_restaurants': [],
            'current_ids': [],
            'week_label': '',
            'all_restaurants': [],
            'selected_count': 0,
        })


@login_required
def coups_de_coeur_save(request):
    """
    Sauvegarde la nouvelle sélection de coups de coeur dans Firestore.
    """
    if request.method != 'POST':
        return redirect('scripts_manager:coups_de_coeur_manage')

    try:
        db = get_firestore_client(request)

        # Récupérer les données du formulaire
        restaurant_ids = request.POST.getlist('restaurant_ids')
        week_label = request.POST.get('week_label', '').strip()

        # Nettoyer les IDs vides
        restaurant_ids = [rid.strip() for rid in restaurant_ids if rid.strip()]

        # Sauvegarder dans Firestore
        doc_ref = db.collection('coups_de_coeur').document('current')
        doc_ref.set({
            'restaurantIds': restaurant_ids,
            'weekLabel': week_label,
            'updatedAt': datetime.now(),
        })

        count = len(restaurant_ids)
        messages.success(
            request,
            f"Coups de coeur mis à jour ! {count} restaurant(s) sélectionné(s)."
        )

    except Exception as e:
        messages.error(request, f"Erreur lors de la sauvegarde : {str(e)}")

    return redirect('scripts_manager:coups_de_coeur_manage')


@login_required
def coups_de_coeur_export(request):
    """Exporte les coups de coeur actuels en CSV ou Excel."""
    fmt = request.GET.get('format', 'csv')

    try:
        db = get_firestore_client(request)
        doc = db.collection('coups_de_coeur').document('current').get()

        rows = []
        if doc.exists:
            data = doc.to_dict()
            restaurant_ids = data.get('restaurantIds', [])
            for rid in restaurant_ids:
                rdoc = db.collection('restaurants').document(rid).get()
                if rdoc.exists:
                    rdata = rdoc.to_dict()
                    rows.append({
                        'Nom': rdata.get('name', rid),
                        'Cuisine': rdata.get('cuisine', ''),
                        'Arrondissement': rdata.get('arrondissement', ''),
                        'Prix': rdata.get('prix', ''),
                    })

        if fmt == 'xlsx':
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Coups de coeur'
            headers = ['Nom', 'Cuisine', 'Arrondissement', 'Prix']
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
            response['Content-Disposition'] = 'attachment; filename="coups_de_coeur.xlsx"'
            return response
        else:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="coups_de_coeur.csv"'
            response.write('\ufeff')
            writer = csv.DictWriter(response, fieldnames=['Nom', 'Cuisine', 'Arrondissement', 'Prix'])
            writer.writeheader()
            writer.writerows(rows)
            return response

    except Exception as e:
        messages.error(request, f"Erreur lors de l'export : {str(e)}")
        return redirect('scripts_manager:coups_de_coeur_manage')
