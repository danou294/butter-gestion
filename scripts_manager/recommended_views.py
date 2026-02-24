"""
Views pour la gestion des "Recommandés pour toi"
Fonctionne via la collection Firestore 'guides' — le guide avec isFeatured=true
est celui affiché dans la section "Recommandés pour toi" de la home.
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

        # Trouver le guide featured actuel
        guides_ref = db.collection('guides')
        all_guides = list(guides_ref.stream())

        featured_doc = None
        featured_data = None
        for g in all_guides:
            gdata = g.to_dict()
            if gdata.get('isFeatured') is True:
                featured_doc = g
                featured_data = gdata
                break

        current_ids = []
        guide_name = ''
        updated_at = None

        if featured_data:
            current_ids = featured_data.get('restaurantIds', [])
            guide_name = featured_data.get('name', '')
            updated_at = featured_data.get('updatedAt')

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
            'guide_name': guide_name,
            'updated_at': updated_at,
            'all_restaurants': all_restaurants,
            'selected_count': len(selected_restaurants),
            'has_featured_guide': featured_doc is not None,
            'featured_guide_id': featured_doc.id if featured_doc else None,
        }

        return render(request, 'scripts_manager/recommended/manage.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement des recommandés : {str(e)}")
        return render(request, 'scripts_manager/recommended/manage.html', {
            'selected_restaurants': [],
            'current_ids': [],
            'guide_name': '',
            'all_restaurants': [],
            'selected_count': 0,
            'has_featured_guide': False,
            'featured_guide_id': None,
        })


@login_required
def recommended_save(request):
    """
    Sauvegarde la nouvelle sélection de recommandés dans le guide featured.
    Crée le guide s'il n'existe pas encore.
    """
    if request.method != 'POST':
        return redirect('scripts_manager:recommended_manage')

    try:
        db = get_firestore_client(request)

        restaurant_ids = request.POST.getlist('restaurant_ids')
        restaurant_ids = [rid.strip() for rid in restaurant_ids if rid.strip()]

        featured_guide_id = request.POST.get('featured_guide_id', '').strip()

        if featured_guide_id:
            # Mettre à jour le guide existant
            doc_ref = db.collection('guides').document(featured_guide_id)
            doc_ref.update({
                'restaurantIds': restaurant_ids,
                'updatedAt': datetime.now(),
            })
        else:
            # Créer un nouveau guide featured
            doc_ref = db.collection('guides').document()
            doc_ref.set({
                'name': 'Recommandés pour toi',
                'restaurantIds': restaurant_ids,
                'isFeatured': True,
                'isPremium': False,
                'order': 0,
                'createdAt': datetime.now(),
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

        # Trouver le guide featured
        guides_ref = db.collection('guides')
        current_ids = []
        for g in guides_ref.stream():
            gdata = g.to_dict()
            if gdata.get('isFeatured') is True:
                current_ids = gdata.get('restaurantIds', [])
                break

        rows = []
        for rid in current_ids:
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
