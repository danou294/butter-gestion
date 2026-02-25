"""
Views pour la gestion des Annonces (Événements et Sondages) dans le backoffice Django
Écrit directement dans Firestore (collection 'announcements')
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from datetime import datetime
import json
import csv

from .firebase_utils import get_firestore_client, get_storage_client


# ==================== LISTE DES ANNONCES ====================

@login_required
def announcements_list(request):
    """
    Affiche la liste de toutes les annonces (événements + sondages)
    """
    try:
        db = get_firestore_client()
        announcements_ref = db.collection('announcements')
        
        # Récupérer toutes les annonces triées par date de création (plus récent en premier)
        announcements_docs = announcements_ref.order_by('createdAt', direction='DESCENDING').stream()
        
        announcements = []
        events_count = 0
        polls_count = 0
        premium_count = 0
        active_count = 0
        
        for doc in announcements_docs:
            data = doc.to_dict()
            data['id'] = doc.id
            announcements.append(data)
            
            # Compter par type
            if data.get('type') == 'event':
                events_count += 1
            elif data.get('type') == 'poll':
                polls_count += 1
            
            if data.get('isPremium', False):
                premium_count += 1
            
            if data.get('isActive', False):
                active_count += 1
        
        context = {
            'announcements': announcements,
            'total_count': len(announcements),
            'events_count': events_count,
            'polls_count': polls_count,
            'premium_count': premium_count,
            'active_count': active_count,
        }
        
        return render(request, 'scripts_manager/announcements/list.html', context)
    
    except Exception as e:
        messages.error(request, f"Erreur lors du chargement des annonces : {str(e)}")
        return render(request, 'scripts_manager/announcements/list.html', {
            'announcements': [],
            'total_count': 0,
            'events_count': 0,
            'polls_count': 0,
            'premium_count': 0,
            'active_count': 0,
        })


# ==================== DÉTAIL D'UNE ANNONCE ====================

@login_required
def announcement_detail(request, announcement_id):
    """
    Affiche le détail d'une annonce avec statistiques
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection('announcements').document(announcement_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('announcements_list')
        
        announcement_data = doc.to_dict()
        announcement_data['id'] = doc.id
        
        # Si c'est un sondage, récupérer les statistiques
        poll_stats = None
        if announcement_data.get('type') == 'poll':
            poll_stats = _get_poll_statistics(db, announcement_id)
        
        # Si c'est un événement, récupérer les clics
        event_stats = None
        if announcement_data.get('type') == 'event':
            event_stats = _get_event_statistics(db, announcement_id)
        
        context = {
            'announcement': announcement_data,
            'poll_stats': poll_stats,
            'event_stats': event_stats,
        }
        
        return render(request, 'scripts_manager/announcements/detail.html', context)
    
    except Exception as e:
        messages.error(request, f"Erreur lors du chargement de l'annonce : {str(e)}")
        return redirect('announcements_list')


def _get_poll_statistics(db, poll_id):
    """Récupère les statistiques d'un sondage"""
    try:
        answers_ref = db.collection('poll_answers').where('pollId', '==', poll_id)
        answers_docs = answers_ref.stream()
        
        answers = []
        answer_counts = {}
        total_votes = 0
        
        for doc in answers_docs:
            data = doc.to_dict()
            answer = data.get('answer', '').lower()
            answers.append(data)
            total_votes += 1
            
            # Compter les occurrences
            if answer in answer_counts:
                answer_counts[answer] += 1
            else:
                answer_counts[answer] = 1
        
        # Trier par nombre de votes (décroissant)
        sorted_answers = sorted(answer_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'total_votes': total_votes,
            'unique_answers': len(answer_counts),
            'top_answers': sorted_answers[:10],  # Top 10
            'all_answers': answers,
        }
    except Exception as e:
        print(f"Error fetching poll stats: {e}")
        return None


def _get_event_statistics(db, event_id):
    """Récupère les statistiques d'un événement"""
    try:
        clicks_ref = db.collection('event_clicks').where('eventId', '==', event_id)
        clicks_docs = clicks_ref.stream()
        
        total_clicks = 0
        unique_users = set()
        
        for doc in clicks_docs:
            data = doc.to_dict()
            total_clicks += 1
            user_id = data.get('userId')
            if user_id:
                unique_users.add(user_id)
        
        return {
            'total_clicks': total_clicks,
            'unique_users': len(unique_users),
        }
    except Exception as e:
        print(f"Error fetching event stats: {e}")
        return None


# ==================== CRÉER UNE ANNONCE ====================

@login_required
def announcement_create(request):
    """
    Formulaire de création d'une annonce
    """
    if request.method == 'POST':
        try:
            db = get_firestore_client()
            
            # Récupérer les données du formulaire
            announcement_id = request.POST.get('id', '').strip().upper()
            announcement_type = request.POST.get('type', 'event').strip()
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            image_url = request.POST.get('imageUrl', '').strip()
            is_premium = request.POST.get('isPremium') == 'on'
            is_active = request.POST.get('isActive') == 'on'
            
            # Dates
            start_date_str = request.POST.get('startDate', '').strip()
            end_date_str = request.POST.get('endDate', '').strip()
            
            # Validation de base
            if not announcement_id or not title:
                messages.error(request, "L'ID et le titre sont requis")
                return render(request, 'scripts_manager/announcements/form.html', {
                    'form_data': request.POST,
                    'mode': 'create'
                })
            
            # Vérifier que l'ID n'existe pas déjà
            doc_ref = db.collection('announcements').document(announcement_id)
            if doc_ref.get().exists:
                messages.error(request, f"Une annonce avec l'ID '{announcement_id}' existe déjà")
                return render(request, 'scripts_manager/announcements/form.html', {
                    'form_data': request.POST,
                    'mode': 'create'
                })
            
            # Parser les dates
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
            
            # Données communes
            announcement_data = {
                'id': announcement_id,
                'type': announcement_type,
                'title': title,
                'description': description,
                'imageUrl': image_url if image_url else None,
                'isPremium': is_premium,
                'isActive': is_active,
                'startDate': start_date,
                'endDate': end_date,
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
            }
            
            # Données spécifiques selon le type
            if announcement_type == 'event':
                cta_text = request.POST.get('ctaText', '').strip()
                cta_link = request.POST.get('ctaLink', '').strip()
                event_date_str = request.POST.get('eventDate', '').strip()
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else None
                
                announcement_data.update({
                    'ctaText': cta_text if cta_text else 'En savoir plus',
                    'ctaLink': cta_link,
                    'eventDate': event_date,
                })
            elif announcement_type == 'poll':
                poll_question = request.POST.get('pollQuestion', '').strip()
                announcement_data.update({
                    'pollQuestion': poll_question if poll_question else title,
                })
            
            # Créer le document
            doc_ref.set(announcement_data)
            
            type_label = "Événement" if announcement_type == 'event' else "Sondage"
            messages.success(request, f"{type_label} '{title}' créé avec succès !")
            return redirect('announcement_detail', announcement_id=announcement_id)
        
        except ValueError as e:
            messages.error(request, f"Erreur de validation : {str(e)}")
            return render(request, 'scripts_manager/announcements/form.html', {
                'form_data': request.POST,
                'mode': 'create'
            })
        except Exception as e:
            messages.error(request, f"Erreur lors de la création : {str(e)}")
            return render(request, 'scripts_manager/announcements/form.html', {
                'form_data': request.POST,
                'mode': 'create'
            })
    
    # GET request
    return render(request, 'scripts_manager/announcements/form.html', {'mode': 'create'})


# ==================== ÉDITER UNE ANNONCE ====================

@login_required
def announcement_edit(request, announcement_id):
    """
    Formulaire d'édition d'une annonce
    """
    db = get_firestore_client()
    doc_ref = db.collection('announcements').document(announcement_id)
    
    if request.method == 'POST':
        try:
            doc = doc_ref.get()
            if not doc.exists:
                messages.error(request, f"Annonce '{announcement_id}' non trouvée")
                return redirect('announcements_list')
            
            # Récupérer les données
            announcement_type = request.POST.get('type', 'event').strip()
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            image_url = request.POST.get('imageUrl', '').strip()
            is_premium = request.POST.get('isPremium') == 'on'
            is_active = request.POST.get('isActive') == 'on'
            
            start_date_str = request.POST.get('startDate', '').strip()
            end_date_str = request.POST.get('endDate', '').strip()
            
            if not title:
                messages.error(request, "Le titre est requis")
                return redirect('announcement_edit', announcement_id=announcement_id)
            
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
            
            update_data = {
                'type': announcement_type,
                'title': title,
                'description': description,
                'imageUrl': image_url if image_url else None,
                'isPremium': is_premium,
                'isActive': is_active,
                'startDate': start_date,
                'endDate': end_date,
                'updatedAt': datetime.utcnow(),
            }
            
            if announcement_type == 'event':
                cta_text = request.POST.get('ctaText', '').strip()
                cta_link = request.POST.get('ctaLink', '').strip()
                event_date_str = request.POST.get('eventDate', '').strip()
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else None
                
                update_data.update({
                    'ctaText': cta_text,
                    'ctaLink': cta_link,
                    'eventDate': event_date,
                })
            elif announcement_type == 'poll':
                poll_question = request.POST.get('pollQuestion', '').strip()
                update_data.update({
                    'pollQuestion': poll_question,
                })
            
            doc_ref.update(update_data)
            
            type_label = "Événement" if announcement_type == 'event' else "Sondage"
            messages.success(request, f"{type_label} '{title}' mis à jour avec succès !")
            return redirect('announcement_detail', announcement_id=announcement_id)
        
        except Exception as e:
            messages.error(request, f"Erreur lors de la mise à jour : {str(e)}")
            return redirect('announcement_edit', announcement_id=announcement_id)
    
    # GET request
    try:
        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('announcements_list')
        
        announcement_data = doc.to_dict()
        announcement_data['id'] = announcement_id
        
        # Formater les dates pour les inputs
        if announcement_data.get('startDate'):
            announcement_data['startDate_formatted'] = announcement_data['startDate'].strftime('%Y-%m-%d')
        if announcement_data.get('endDate'):
            announcement_data['endDate_formatted'] = announcement_data['endDate'].strftime('%Y-%m-%d')
        if announcement_data.get('eventDate'):
            announcement_data['eventDate_formatted'] = announcement_data['eventDate'].strftime('%Y-%m-%d')
        
        context = {
            'announcement': announcement_data,
            'announcement_id': announcement_id,
            'mode': 'edit'
        }
        
        return render(request, 'scripts_manager/announcements/form.html', context)
    
    except Exception as e:
        messages.error(request, f"Erreur lors du chargement : {str(e)}")
        return redirect('announcements_list')


# ==================== SUPPRIMER UNE ANNONCE ====================

@login_required
@require_http_methods(["POST"])
def announcement_delete(request, announcement_id):
    """
    Supprime une annonce de Firestore
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection('announcements').document(announcement_id)
        
        doc = doc_ref.get()
        if not doc.exists:
            messages.error(request, f"Annonce '{announcement_id}' non trouvée")
            return redirect('announcements_list')
        
        announcement_title = doc.to_dict().get('title', announcement_id)
        
        doc_ref.delete()
        
        messages.success(request, f"Annonce '{announcement_title}' supprimée avec succès")
        return redirect('announcements_list')
    
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression : {str(e)}")
        return redirect('announcements_list')


# ==================== EXPORT RÉPONSES SONDAGE ====================

@login_required
def poll_export_answers(request, poll_id):
    """
    Exporte les réponses d'un sondage en CSV
    """
    try:
        db = get_firestore_client()
        
        # Vérifier que le sondage existe
        poll_doc = db.collection('announcements').document(poll_id).get()
        if not poll_doc.exists:
            messages.error(request, f"Sondage '{poll_id}' non trouvé")
            return redirect('announcements_list')
        
        poll_data = poll_doc.to_dict()
        poll_title = poll_data.get('title', poll_id)
        
        # Récupérer toutes les réponses
        answers_ref = db.collection('poll_answers').where('pollId', '==', poll_id)
        answers_docs = answers_ref.stream()
        
        # Créer le CSV
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="poll_{poll_id}_answers.csv"'
        response.write('\ufeff')  # BOM UTF-8
        
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['User ID', 'Réponse', 'Date'])
        
        for doc in answers_docs:
            data = doc.to_dict()
            user_id = data.get('userId', '')
            answer = data.get('answer', '')
            submitted_at = data.get('submittedAt')
            date_str = submitted_at.strftime('%Y-%m-%d %H:%M:%S') if submitted_at else ''
            
            writer.writerow([user_id, answer, date_str])
        
        return response
    
    except Exception as e:
        messages.error(request, f"Erreur lors de l'export : {str(e)}")
        return redirect('announcement_detail', announcement_id=poll_id)


# ==================== EXPORT JSON ====================

@login_required
def announcement_get_json(request, announcement_id):
    """
    Retourne le JSON d'une annonce
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection('announcements').document(announcement_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return JsonResponse({'error': 'Annonce non trouvée'}, status=404)
        
        announcement_data = doc.to_dict()
        announcement_data['id'] = doc.id
        
        # Convertir les timestamps
        for key in ['createdAt', 'updatedAt', 'startDate', 'endDate', 'eventDate']:
            if key in announcement_data and announcement_data[key]:
                announcement_data[key] = announcement_data[key].isoformat() if hasattr(announcement_data[key], 'isoformat') else str(announcement_data[key])
        
        return JsonResponse(announcement_data, json_dumps_params={'indent': 2})
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
