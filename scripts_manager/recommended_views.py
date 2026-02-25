"""
Views pour la gestion des "Recommandés pour toi"
Collection Firestore : recommended (document 'current')
Structure : { restaurantIds: [...], updatedAt: timestamp }

Indépendant des "Coups de coeur de la semaine" (collection coups_de_coeur).
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
def recommended_manage(request):
    """
    Page de gestion des recommandés : affiche la sélection actuelle
    et permet d'ajouter/retirer/réordonner des restaurants.
    """
    try:
        db = get_firestore_client(request)
        bucket_name = get_firebase_bucket(request)

        # Charger la sélection actuelle
        doc_ref = db.collection('recommended').document('current')
        doc = doc_ref.get()

        current_ids = []
        updated_at = None

        if doc.exists:
            data = doc.to_dict()
            current_ids = data.get('restaurantIds', [])
            updated_at = data.get('updatedAt')

        # Charger les restaurants sélectionnés avec leurs détails
        selected_restaurants = []
        if current_ids:
            for rid in current_ids:
                rdoc = db.collection('restaurants').document(rid).get()
                if rdoc.exists:
                    rdata = rdoc.to_dict()
                    rdata['id'] = rdoc.id
                    logo_ref = rdata.get('logoUrl') or rdata.get('logo', '')
                    if logo_ref and not logo_ref.startswith('http'):
                        import urllib.parse
                        path = f"Logos/{logo_ref}.webp"
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
            'updated_at': updated_at,
            'all_restaurants': all_restaurants,
            'selected_count': len(selected_restaurants),
        }

        return render(request, 'scripts_manager/recommended/manage.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement des recommandés : {str(e)}")
        return render(request, 'scripts_manager/recommended/manage.html', {
            'selected_restaurants': [],
            'current_ids': [],
            'all_restaurants': [],
            'selected_count': 0,
        })


@login_required
def recommended_save(request):
    """
    Sauvegarde la nouvelle sélection de recommandés dans Firestore.
    """
    if request.method != 'POST':
        return redirect('scripts_manager:recommended_manage')

    try:
        db = get_firestore_client(request)

        restaurant_ids = request.POST.getlist('restaurant_ids')
        restaurant_ids = [rid.strip() for rid in restaurant_ids if rid.strip()]

        # Sauvegarder dans Firestore
        doc_ref = db.collection('recommended').document('current')
        doc_ref.set({
            'restaurantIds': restaurant_ids,
            'updatedAt': datetime.now(),
        })

        count = len(restaurant_ids)
        messages.success(
            request,
            f"Recommandés mis à jour ! {count} restaurant(s) sélectionné(s)."
        )

    except Exception as e:
        messages.error(request, f"Erreur lors de la sauvegarde : {str(e)}")

    return redirect('scripts_manager:recommended_manage')


@login_required
def recommended_export(request):
    """Exporte les recommandés actuels en CSV ou Excel."""
    fmt = request.GET.get('format', 'csv')

    try:
        db = get_firestore_client(request)
        doc = db.collection('recommended').document('current').get()

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
            ws.title = 'Recommandés'
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
            response['Content-Disposition'] = 'attachment; filename="recommandes.xlsx"'
            return response
        else:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="recommandes.csv"'
            response.write('\ufeff')
            writer = csv.DictWriter(response, fieldnames=['Nom', 'Cuisine', 'Arrondissement', 'Prix'])
            writer.writeheader()
            writer.writerows(rows)
            return response

    except Exception as e:
        messages.error(request, f"Erreur lors de l'export : {str(e)}")
        return redirect('scripts_manager:recommended_manage')
