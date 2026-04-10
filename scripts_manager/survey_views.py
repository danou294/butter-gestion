"""
Views pour la gestion des sondages in-app.
Collection Firestore : survey_config (document 'active')
Collection Firestore : survey_responses (un doc par user × restaurant × survey)
"""

import json
import csv
import logging
from datetime import datetime
from io import StringIO

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse

from .restaurants_views import get_firestore_client

logger = logging.getLogger(__name__)

CONFIG_COLLECTION = 'survey_config'
CONFIG_DOC_ID = 'active'
RESPONSES_COLLECTION = 'survey_responses'

VALID_POSITIONS = [
    'above_reviews',
    'above_information',
    'below_social',
    'below_photos',
    'below_description',
]

VALID_TARGET_TYPES = [
    'restaurant',
    'bar',
    'hotel',
    'daypass',
    'all',
]

POSITION_LABELS = {
    'above_reviews': 'Au-dessus des avis',
    'above_information': 'Au-dessus des informations',
    'below_social': 'Sous les boutons sociaux',
    'below_photos': 'Après les photos',
    'below_description': 'Après la description',
}

DEFAULT_SURVEY = {
    'id': 'survey_1',
    'enabled': True,
    'position': 'above_reviews',
    'showResults': False,
    'targetTypes': ['restaurant'],
    'questions': [
        {
            'id': 'q1',
            'text': 'Est-ce que tu recommanderais ce restaurant ?',
            'showIf': None,
            'order': 1,
        },
        {
            'id': 'q2',
            'text': 'Est-ce que tu y retournerais ?',
            'showIf': {'questionId': 'q1', 'answer': True},
            'order': 2,
        },
        {
            'id': 'q3',
            'text': 'Est-ce que le rapport qualité/prix est bon ?',
            'showIf': {'questionId': 'q1', 'answer': True},
            'order': 3,
        },
        {
            'id': 'q4',
            'text': 'Tu as trouvé ça trop cher ?',
            'showIf': {'questionId': 'q1', 'answer': False},
            'order': 4,
        },
    ],
}


@login_required
def survey_list(request):
    """Liste de tous les sondages."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
            surveys = data.get('surveys', [])
        else:
            surveys = []

        return render(request, 'scripts_manager/surveys/list.html', {
            'surveys_json': json.dumps(surveys, ensure_ascii=False, default=str),
            'position_labels_json': json.dumps(POSITION_LABELS, ensure_ascii=False),
            'valid_target_types_json': json.dumps(VALID_TARGET_TYPES, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur chargement surveys: {e}")
        messages.error(request, f"Erreur : {e}")
        return render(request, 'scripts_manager/surveys/list.html', {
            'surveys_json': '[]',
            'position_labels_json': json.dumps(POSITION_LABELS, ensure_ascii=False),
            'valid_target_types_json': json.dumps(VALID_TARGET_TYPES, ensure_ascii=False),
        })


@login_required
def survey_edit(request, survey_id=None):
    """Page d'édition d'un sondage (nouveau ou existant)."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()

        survey = None
        if doc.exists and survey_id:
            data = doc.to_dict()
            for s in data.get('surveys', []):
                if s.get('id') == survey_id:
                    survey = s
                    break

        if not survey and survey_id:
            messages.error(request, f"Sondage '{survey_id}' introuvable.")
            return redirect('scripts_manager:survey_list')

        if not survey:
            # Nouveau sondage
            survey = {
                'id': '',
                'enabled': False,
                'showResults': False,
                'position': 'above_reviews',
                'targetTypes': ['restaurant'],
                'questions': [],
            }

        return render(request, 'scripts_manager/surveys/edit.html', {
            'survey_json': json.dumps(survey, ensure_ascii=False, default=str),
            'is_new': not survey_id,
            'position_labels_json': json.dumps(POSITION_LABELS, ensure_ascii=False),
            'valid_positions_json': json.dumps(VALID_POSITIONS, ensure_ascii=False),
            'valid_target_types_json': json.dumps(VALID_TARGET_TYPES, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur chargement survey: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')


@login_required
@require_http_methods(["POST"])
def survey_save(request):
    """Sauvegarde un sondage dans survey_config/active."""
    try:
        raw = request.POST.get('survey_data', '{}')
        survey = json.loads(raw)

        survey_id = (survey.get('id') or '').strip()
        if not survey_id:
            messages.error(request, "L'ID du sondage est obligatoire.")
            return redirect('scripts_manager:survey_list')

        position = survey.get('position', 'above_reviews')
        if position not in VALID_POSITIONS:
            position = 'above_reviews'

        target_types = survey.get('targetTypes', ['restaurant'])
        target_types = [t for t in target_types if t in VALID_TARGET_TYPES]
        if not target_types:
            target_types = ['restaurant']

        enabled = bool(survey.get('enabled', False))
        show_results = bool(survey.get('showResults', False))

        questions = []
        for q in survey.get('questions', []):
            text = (q.get('text') or '').strip()
            if not text:
                continue
            qid = (q.get('id') or '').strip()
            if not qid:
                continue
            show_if = q.get('showIf')
            if show_if and isinstance(show_if, dict):
                show_if = {
                    'questionId': show_if.get('questionId', ''),
                    'answer': bool(show_if.get('answer', True)),
                }
            else:
                show_if = None
            questions.append({
                'id': qid,
                'text': text,
                'showIf': show_if,
                'order': int(q.get('order', 0)),
            })

        clean_survey = {
            'id': survey_id,
            'enabled': enabled,
            'showResults': show_results,
            'position': position,
            'targetTypes': target_types,
            'questions': questions,
        }

        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
            surveys = data.get('surveys', [])
        else:
            surveys = []

        # Upsert
        found = False
        for i, s in enumerate(surveys):
            if s.get('id') == survey_id:
                surveys[i] = clean_survey
                found = True
                break
        if not found:
            surveys.append(clean_survey)

        db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set({
            'surveys': surveys,
            'updatedAt': datetime.utcnow(),
        })

        messages.success(request, f"Sondage '{survey_id}' sauvegardé.")
    except json.JSONDecodeError:
        messages.error(request, "Données invalides.")
    except Exception as e:
        logger.error(f"Erreur sauvegarde survey: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:survey_list')


@login_required
@require_http_methods(["POST"])
def survey_delete(request, survey_id):
    """Supprime un sondage."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
            surveys = [s for s in data.get('surveys', []) if s.get('id') != survey_id]
            db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set({
                'surveys': surveys,
                'updatedAt': datetime.utcnow(),
            })
            messages.success(request, f"Sondage '{survey_id}' supprimé.")
        else:
            messages.error(request, "Aucune config trouvée.")
    except Exception as e:
        logger.error(f"Erreur suppression survey: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:survey_list')


@login_required
@require_http_methods(["POST"])
def survey_seed(request):
    """Crée le sondage par défaut."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()

        if doc.exists:
            data = doc.to_dict()
            surveys = data.get('surveys', [])
        else:
            surveys = []

        # Vérifier si survey_1 existe déjà
        if any(s.get('id') == 'survey_1' for s in surveys):
            messages.warning(request, "Le sondage par défaut existe déjà.")
        else:
            surveys.append(DEFAULT_SURVEY)
            db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set({
                'surveys': surveys,
                'updatedAt': datetime.utcnow(),
            })
            messages.success(request, "Sondage par défaut créé.")
    except Exception as e:
        logger.error(f"Erreur seed survey: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:survey_list')


@login_required
def survey_results(request, survey_id):
    """Dashboard des résultats d'un sondage."""
    try:
        db = get_firestore_client(request)

        # Charger le sondage
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()
        survey = None
        if doc.exists:
            for s in doc.to_dict().get('surveys', []):
                if s.get('id') == survey_id:
                    survey = s
                    break

        if not survey:
            messages.error(request, f"Sondage '{survey_id}' introuvable.")
            return redirect('scripts_manager:survey_list')

        # Charger les réponses
        responses_docs = db.collection(RESPONSES_COLLECTION)\
            .where('surveyId', '==', survey_id).get()

        responses = []
        for rdoc in responses_docs:
            rdata = rdoc.to_dict()
            rdata['_docId'] = rdoc.id
            responses.append(rdata)

        # Calculer les stats par question
        question_stats = {}
        for q in survey.get('questions', []):
            qid = q['id']
            yes_count = sum(1 for r in responses if r.get('responses', {}).get(qid) is True)
            no_count = sum(1 for r in responses if r.get('responses', {}).get(qid) is False)
            total = yes_count + no_count
            question_stats[qid] = {
                'text': q['text'],
                'yes': yes_count,
                'no': no_count,
                'total': total,
                'yes_pct': round(yes_count / total * 100) if total else 0,
                'no_pct': round(no_count / total * 100) if total else 0,
            }

        # Restaurants uniques
        restaurant_ids = sorted(set(r.get('restaurantId', '') for r in responses))

        return render(request, 'scripts_manager/surveys/results.html', {
            'survey_json': json.dumps(survey, ensure_ascii=False, default=str),
            'responses_json': json.dumps(responses, ensure_ascii=False, default=str),
            'question_stats_json': json.dumps(question_stats, ensure_ascii=False),
            'total_responses': len(responses),
            'completed_responses': sum(1 for r in responses if r.get('completed')),
            'restaurant_ids_json': json.dumps(restaurant_ids, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur résultats survey: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')


@login_required
def survey_export_csv(request, survey_id):
    """Export CSV des réponses d'un sondage."""
    try:
        db = get_firestore_client(request)

        # Charger le sondage
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()
        survey = None
        if doc.exists:
            for s in doc.to_dict().get('surveys', []):
                if s.get('id') == survey_id:
                    survey = s
                    break

        if not survey:
            messages.error(request, "Sondage introuvable.")
            return redirect('scripts_manager:survey_list')

        # Charger les réponses
        responses_docs = db.collection(RESPONSES_COLLECTION)\
            .where('surveyId', '==', survey_id).get()

        questions = sorted(survey.get('questions', []), key=lambda q: q.get('order', 0))
        q_ids = [q['id'] for q in questions]
        q_texts = {q['id']: q['text'] for q in questions}

        output = StringIO()
        writer = csv.writer(output)

        # Header
        header = ['userId', 'restaurantId', 'completed', 'completedAt']
        for qid in q_ids:
            header.append(f"{qid} - {q_texts[qid]}")
        writer.writerow(header)

        # Rows
        for rdoc in responses_docs:
            rdata = rdoc.to_dict()
            row = [
                rdata.get('userId', ''),
                rdata.get('restaurantId', ''),
                rdata.get('completed', False),
                str(rdata.get('completedAt', '')),
            ]
            for qid in q_ids:
                answer = rdata.get('responses', {}).get(qid)
                if answer is True:
                    row.append('Oui')
                elif answer is False:
                    row.append('Non')
                else:
                    row.append('')
            writer.writerow(row)

        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="survey_{survey_id}_responses.csv"'
        return response

    except Exception as e:
        logger.error(f"Erreur export survey CSV: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')
