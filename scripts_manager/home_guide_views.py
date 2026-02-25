"""
Views pour la sélection du guide affiché sur la page d'accueil.
Collection Firestore : home_guide (document 'current')
Structure : { guideId: "...", updatedAt: timestamp }
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import datetime

from .restaurants_views import get_firestore_client


@login_required
def home_guide_manage(request):
    """
    Page pour sélectionner quel guide s'affiche sur la home.
    """
    try:
        db = get_firestore_client(request)

        # Charger le guide actuellement sélectionné
        doc_ref = db.collection('home_guide').document('current')
        doc = doc_ref.get()

        selected_guide_id = ''
        updated_at = None

        if doc.exists:
            data = doc.to_dict()
            selected_guide_id = data.get('guideId', '')
            updated_at = data.get('updatedAt')

        # Charger tous les guides disponibles
        all_guides = []
        for gdoc in db.collection('guides').order_by('order').stream():
            gdata = gdoc.to_dict()
            all_guides.append({
                'id': gdoc.id,
                'name': gdata.get('name', gdoc.id),
                'description': gdata.get('description', ''),
                'restaurant_count': len(gdata.get('restaurantIds', [])),
                'isPremium': gdata.get('isPremium', False),
                'isFeatured': gdata.get('isFeatured', False),
                'order': gdata.get('order', 0),
            })

        context = {
            'selected_guide_id': selected_guide_id,
            'updated_at': updated_at,
            'all_guides': all_guides,
        }

        return render(request, 'scripts_manager/home_guide/manage.html', context)

    except Exception as e:
        messages.error(request, f"Erreur lors du chargement : {str(e)}")
        return render(request, 'scripts_manager/home_guide/manage.html', {
            'selected_guide_id': '',
            'all_guides': [],
        })


@login_required
def home_guide_save(request):
    """
    Sauvegarde le guide sélectionné pour la home.
    """
    if request.method != 'POST':
        return redirect('scripts_manager:home_guide_manage')

    try:
        db = get_firestore_client(request)

        guide_id = request.POST.get('guide_id', '').strip()

        if not guide_id:
            # Supprimer la sélection
            db.collection('home_guide').document('current').delete()
            messages.success(request, "Guide de la home supprimé. Un guide aléatoire sera affiché.")
        else:
            # Vérifier que le guide existe
            guide_doc = db.collection('guides').document(guide_id).get()
            if not guide_doc.exists:
                messages.error(request, f"Guide '{guide_id}' non trouvé.")
                return redirect('scripts_manager:home_guide_manage')

            guide_name = guide_doc.to_dict().get('name', guide_id)

            db.collection('home_guide').document('current').set({
                'guideId': guide_id,
                'updatedAt': datetime.now(),
            })

            messages.success(request, f"Guide de la home mis à jour : \"{guide_name}\"")

    except Exception as e:
        messages.error(request, f"Erreur lors de la sauvegarde : {str(e)}")

    return redirect('scripts_manager:home_guide_manage')
