"""
Vues pour la gestion des restaurants Marrakech
Filtre la collection Firestore 'restaurants' par city == 'Marrakech'
"""
import csv
import io
import json
import logging
import urllib.parse
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .restaurants_views import get_firestore_client
from .firebase_utils import get_firebase_bucket

logger = logging.getLogger(__name__)

VENUE_TYPES = ['restaurant', 'hotel', 'daypass']
VENUE_TYPE_LABELS = {
    'restaurant': 'Restaurants',
    'hotel': 'Hotels',
    'daypass': 'Day passes',
}


def _build_logo_url(rdata, bucket_name):
    """Construit l'URL du logo Firebase Storage."""
    tag = rdata.get('tag', '')
    if not tag:
        return ''
    path = f"Logos/{tag}1.webp"
    encoded_path = urllib.parse.quote(path, safe='')
    return f"https://firebasestorage.googleapis.com/v0/b/{bucket_name}/o/{encoded_path}?alt=media"


@login_required
def marrakech_list(request):
    """Liste des restaurants Marrakech avec onglets par categorie."""
    active_tab = request.GET.get('type', 'restaurant')
    if active_tab not in VENUE_TYPES:
        active_tab = 'restaurant'

    try:
        db = get_firestore_client(request)
        bucket_name = get_firebase_bucket(request)

        # Charger tous les restaurants Marrakech
        query = db.collection('restaurants').where('city', '==', 'Marrakech')
        docs = list(query.stream())

        all_restaurants = []
        counts = {'restaurant': 0, 'hotel': 0, 'daypass': 0}

        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            vtype = data.get('venue_type', 'restaurant')
            counts[vtype] = counts.get(vtype, 0) + 1
            data['logoUrl'] = _build_logo_url(data, bucket_name)
            all_restaurants.append(data)

        # Filtrer par type
        filtered = [r for r in all_restaurants if r.get('venue_type', 'restaurant') == active_tab]
        filtered.sort(key=lambda r: r.get('name', ''))

        context = {
            'restaurants': filtered,
            'all_count': len(all_restaurants),
            'counts': counts,
            'active_tab': active_tab,
            'venue_type_labels': VENUE_TYPE_LABELS,
        }
        return render(request, 'scripts_manager/marrakech/list.html', context)

    except Exception as e:
        logger.error(f"Erreur marrakech_list: {e}")
        messages.error(request, f"Erreur : {e}")
        return render(request, 'scripts_manager/marrakech/list.html', {
            'restaurants': [],
            'all_count': 0,
            'counts': {'restaurant': 0, 'hotel': 0, 'daypass': 0},
            'active_tab': active_tab,
            'venue_type_labels': VENUE_TYPE_LABELS,
        })


@login_required
def marrakech_detail(request, doc_id):
    """Detail d'un restaurant Marrakech (redirige vers le detail standard)."""
    return redirect('scripts_manager:restaurant_detail', restaurant_id=doc_id)


@login_required
def marrakech_export(request):
    """Exporte les restaurants Marrakech en CSV ou Excel."""
    fmt = request.GET.get('format', 'csv')
    vtype = request.GET.get('type', '')

    try:
        db = get_firestore_client(request)
        query = db.collection('restaurants').where('city', '==', 'Marrakech')
        docs = list(query.stream())

        rows = []
        for doc in docs:
            data = doc.to_dict()
            venue = data.get('venue_type', 'restaurant')
            if vtype and venue != vtype:
                continue
            rows.append({
                'Tag': data.get('tag', ''),
                'Nom': data.get('name', doc.id),
                'Type': venue,
                'Quartier': data.get('arrondissement', ''),
                'Prix': ', '.join(data.get('price_range', [])) if isinstance(data.get('price_range'), list) else str(data.get('price_range', '')),
                'Categorie hotel': data.get('hotel_category', ''),
                'Prix/nuit': data.get('price_per_night', ''),
                'Etoiles': data.get('star_rating', ''),
                'Equipements': ', '.join(data.get('equipements', [])) if isinstance(data.get('equipements'), list) else '',
                'Adresse': data.get('address', ''),
            })

        rows.sort(key=lambda r: r['Nom'])
        headers = ['Tag', 'Nom', 'Type', 'Quartier', 'Prix', 'Categorie hotel', 'Prix/nuit', 'Etoiles', 'Equipements', 'Adresse']

        if fmt == 'xlsx':
            try:
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = 'Marrakech'
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
                response['Content-Disposition'] = 'attachment; filename="marrakech_restaurants.xlsx"'
                return response
            except ImportError:
                messages.error(request, "openpyxl non installe, export CSV uniquement")
                fmt = 'csv'

        # CSV
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="marrakech_restaurants.csv"'
        response.write('\ufeff')
        writer = csv.DictWriter(response, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        return response

    except Exception as e:
        messages.error(request, f"Erreur export : {e}")
        return redirect('scripts_manager:marrakech_list')


@login_required
def marrakech_stats(request):
    """Retourne les stats Marrakech en JSON (pour AJAX)."""
    try:
        db = get_firestore_client(request)
        query = db.collection('restaurants').where('city', '==', 'Marrakech')
        docs = list(query.stream())

        counts = {'restaurant': 0, 'hotel': 0, 'daypass': 0, 'total': 0}
        quartiers = {}

        for doc in docs:
            data = doc.to_dict()
            vtype = data.get('venue_type', 'restaurant')
            counts[vtype] = counts.get(vtype, 0) + 1
            counts['total'] += 1
            q = data.get('arrondissement', 'Inconnu')
            quartiers[q] = quartiers.get(q, 0) + 1

        return JsonResponse({
            'counts': counts,
            'quartiers': quartiers,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
