"""
Views pour la gestion des sondages in-app.
Collection Firestore : survey_config (document 'active')
Collection Firestore : survey_responses (un doc par user × restaurant × survey)

Schéma question (nouveau) :
{
  id: "q1",
  text: "...",
  order: 1,
  showIf: { questionId: "q0", answer: "Oui" } | null,
  current_version_id: "v1",
  versions: {
    v1: {
      answers: ["Oui", "Non"],
      created_at: timestamp,
      vote_counts: { "Oui": 12, "Non": 4 },
      archived_at: timestamp?,  # présent uniquement quand la version est archivée
    },
    ...
  },
  targeting: {
    restaurant_ids: [...] | null,
    filters: {
      cuisines: [...]?, price_range: [...]?, ambiance: [...]?,
      lieu_tag: [...]?, arrondissements: [...]?, moments: [...]?,
    } | null
  } | null,
}

Réponse user (collection survey_responses) :
{
  surveyId, userId, restaurantId,
  responses: { q1: "Oui" },         # string (legacy: bool)
  versionMap: { q1: "v1" },         # version utilisée par le user au moment du vote
  completed, completedAt,
}
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
from django.http import HttpResponse, JsonResponse

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

# Filtres de ciblage : doivent matcher les champs déjà utilisés sur les docs restaurants.
TARGETING_FILTER_KEYS = [
    'cuisines',
    'price_range',
    'ambiance',
    'lieu_tag',
    'arrondissements',
    'moments',
]

TARGETING_FILTER_OPTIONS = {
    'cuisines': ['Italien', 'Méditerranéen', 'Asiatique', 'Français', 'Sud-Américain', 'Indien', 'Américain', 'Africain', 'Japonais', 'Israélien', 'Other'],
    'price_range': ['€', '€€', '€€€', '€€€€'],
    'ambiance': ['Entre amis', 'En famille', 'Date', 'Festif'],
    'lieu_tag': ['Bar', 'Cave à manger', 'Coffee shop', 'Fast', 'Brasserie', 'Hôtel', 'Gastronomique', 'Salle privatisable', 'Terrasse', 'Rooftop'],
    'arrondissements': [
        '75001', '75002', '75003', '75004', '75005', '75006', '75007', '75008', '75009', '75010',
        '75011', '75012', '75013', '75014', '75015', '75016', '75017', '75018', '75019', '75020',
    ],
    'moments': ['Petit-déjeuner', 'Brunch', 'Déjeuner', 'Goûter', 'Drinks', 'Dîner'],
}

TARGETING_FILTER_LABELS = {
    'cuisines': 'Cuisines',
    'price_range': 'Tranche de prix',
    'ambiance': 'Ambiance',
    'lieu_tag': 'Type de lieu',
    'arrondissements': 'Arrondissement',
    'moments': 'Moment',
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
            'current_version_id': 'v1',
            'versions': {
                'v1': {
                    'answers': ['Oui', 'Non'],
                    'created_at': None,  # rempli au save
                    'vote_counts': {'Oui': 0, 'Non': 0},
                }
            },
            'targeting': None,
        },
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy_answer_to_string(answer):
    """Convertit les anciennes réponses booléennes en strings 'Oui'/'Non'."""
    if answer is True:
        return 'Oui'
    if answer is False:
        return 'Non'
    if isinstance(answer, str):
        return answer
    return None


def _compute_vote_counts(db, survey_id, qid, version_id):
    """Calcule les vote_counts pour une question + version donnée à partir de survey_responses."""
    counts = {}
    try:
        docs = db.collection(RESPONSES_COLLECTION).where('surveyId', '==', survey_id).stream()
        for d in docs:
            data = d.to_dict() or {}
            answer = (data.get('responses') or {}).get(qid)
            answer_str = _legacy_answer_to_string(answer)
            if not answer_str:
                continue
            v = (data.get('versionMap') or {}).get(qid, 'v1')
            if v != version_id:
                continue
            counts[answer_str] = counts.get(answer_str, 0) + 1
    except Exception as e:
        logger.warning(f"Impossible de recalculer vote_counts ({survey_id}/{qid}/{version_id}): {e}")
    return counts


def _normalize_targeting(raw):
    """Nettoie le bloc targeting fourni par le formulaire."""
    if not raw or not isinstance(raw, dict):
        return None

    restaurant_ids = raw.get('restaurant_ids')
    if isinstance(restaurant_ids, list):
        cleaned_ids = [str(x).strip() for x in restaurant_ids if str(x).strip()]
        if cleaned_ids:
            return {'restaurant_ids': cleaned_ids, 'filters': None}

    filters = raw.get('filters') or {}
    clean_filters = {}
    if isinstance(filters, dict):
        for k in TARGETING_FILTER_KEYS:
            v = filters.get(k)
            if isinstance(v, list):
                vals = [str(x).strip() for x in v if str(x).strip()]
                if vals:
                    clean_filters[k] = vals
    if clean_filters:
        return {'restaurant_ids': None, 'filters': clean_filters}

    return None


def _normalize_show_if(raw):
    """Garde showIf au format {questionId, answer:string}.
    Convertit les booléens legacy en 'Oui'/'Non'."""
    if not raw or not isinstance(raw, dict):
        return None
    qid = (raw.get('questionId') or '').strip()
    if not qid:
        return None
    ans = raw.get('answer')
    if ans is True:
        ans = 'Oui'
    elif ans is False:
        ans = 'Non'
    elif isinstance(ans, str):
        ans = ans.strip()
    else:
        ans = ''
    if not ans:
        return None
    return {'questionId': qid, 'answer': ans}


def _next_version_id(versions):
    if not versions:
        return 'v1'
    n = 1
    while f'v{n}' in versions:
        n += 1
    return f'v{n}'


def _serialize_survey_for_json(survey):
    """Convertit timestamps Firestore en string pour le JSON."""
    return json.loads(json.dumps(survey, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


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
            survey = {
                'id': '',
                'enabled': False,
                'showResults': False,
                'position': 'above_reviews',
                'targetTypes': ['restaurant'],
                'questions': [],
            }

        return render(request, 'scripts_manager/surveys/edit.html', {
            'survey_json': json.dumps(_serialize_survey_for_json(survey), ensure_ascii=False),
            'is_new': not survey_id,
            'position_labels_json': json.dumps(POSITION_LABELS, ensure_ascii=False),
            'valid_positions_json': json.dumps(VALID_POSITIONS, ensure_ascii=False),
            'valid_target_types_json': json.dumps(VALID_TARGET_TYPES, ensure_ascii=False),
            'targeting_filter_keys_json': json.dumps(TARGETING_FILTER_KEYS, ensure_ascii=False),
            'targeting_filter_options_json': json.dumps(TARGETING_FILTER_OPTIONS, ensure_ascii=False),
            'targeting_filter_labels_json': json.dumps(TARGETING_FILTER_LABELS, ensure_ascii=False),
        })
    except Exception as e:
        logger.error(f"Erreur chargement survey: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')


@login_required
@require_http_methods(["POST"])
def survey_save(request):
    """Sauvegarde un sondage dans survey_config/active.
    Détecte les modifications de réponses → crée une nouvelle version (versioning).
    """
    try:
        raw = request.POST.get('survey_data', '{}')
        new_survey = json.loads(raw)

        survey_id = (new_survey.get('id') or '').strip()
        if not survey_id:
            messages.error(request, "L'ID du sondage est obligatoire.")
            return redirect('scripts_manager:survey_list')

        position = new_survey.get('position', 'above_reviews')
        if position not in VALID_POSITIONS:
            position = 'above_reviews'

        target_types = new_survey.get('targetTypes', ['restaurant'])
        target_types = [t for t in target_types if t in VALID_TARGET_TYPES]
        if not target_types:
            target_types = ['restaurant']

        enabled = bool(new_survey.get('enabled', False))
        show_results = bool(new_survey.get('showResults', False))

        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()
        existing_data = doc.to_dict() if doc.exists else {}
        existing_surveys = existing_data.get('surveys', []) if existing_data else []
        existing_survey = next((s for s in existing_surveys if s.get('id') == survey_id), None)
        existing_questions_by_id = {
            q.get('id'): q for q in (existing_survey.get('questions', []) if existing_survey else [])
        }

        now = datetime.utcnow()
        clean_questions = []
        bumped_versions = []  # pour le message flash

        for q in new_survey.get('questions', []):
            qid = (q.get('id') or '').strip()
            text = (q.get('text') or '').strip()
            if not qid or not text:
                continue

            # Réponses (max 6, déduplique en gardant l'ordre, vire les vides)
            raw_answers = q.get('answers') or []
            seen = set()
            new_answers = []
            for a in raw_answers:
                if not isinstance(a, str):
                    continue
                a = a.strip()
                if not a or a in seen:
                    continue
                seen.add(a)
                new_answers.append(a)
                if len(new_answers) >= 6:
                    break
            if not new_answers:
                # Garde-fou : sans réponse une question est inutile
                new_answers = ['Oui', 'Non']

            existing_q = existing_questions_by_id.get(qid)
            if existing_q:
                versions = dict(existing_q.get('versions') or {})
                current_vid = existing_q.get('current_version_id') or _next_version_id({})
                current_version = versions.get(current_vid) or {}
                current_answers = list(current_version.get('answers') or [])

                if list(new_answers) == current_answers:
                    # Pas de changement → on garde la version courante telle quelle
                    pass
                else:
                    # Snapshot des compteurs sur la version sortante avant archivage
                    archived_counts = _compute_vote_counts(db, survey_id, qid, current_vid)
                    versions[current_vid] = {
                        **current_version,
                        'answers': current_answers,
                        'vote_counts': archived_counts,
                        'archived_at': now,
                    }
                    new_vid = _next_version_id(versions)
                    versions[new_vid] = {
                        'answers': new_answers,
                        'created_at': now,
                        'vote_counts': {a: 0 for a in new_answers},
                    }
                    current_vid = new_vid
                    bumped_versions.append(qid)
            else:
                # Nouvelle question
                versions = {
                    'v1': {
                        'answers': new_answers,
                        'created_at': now,
                        'vote_counts': {a: 0 for a in new_answers},
                    }
                }
                current_vid = 'v1'

            clean_q = {
                'id': qid,
                'text': text,
                'order': int(q.get('order') or 0),
                'showIf': _normalize_show_if(q.get('showIf')),
                'current_version_id': current_vid,
                'versions': versions,
                'targeting': _normalize_targeting(q.get('targeting')),
            }
            clean_questions.append(clean_q)

        clean_survey = {
            'id': survey_id,
            'enabled': enabled,
            'showResults': show_results,
            'position': position,
            'targetTypes': target_types,
            'questions': clean_questions,
        }

        # Upsert
        found = False
        for i, s in enumerate(existing_surveys):
            if s.get('id') == survey_id:
                existing_surveys[i] = clean_survey
                found = True
                break
        if not found:
            existing_surveys.append(clean_survey)

        db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set({
            'surveys': existing_surveys,
            'updatedAt': now,
        })

        if bumped_versions:
            messages.success(
                request,
                f"Sondage '{survey_id}' sauvegardé. Nouvelle version pour : {', '.join(bumped_versions)}."
            )
        else:
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

        if any(s.get('id') == 'survey_1' for s in surveys):
            messages.warning(request, "Le sondage par défaut existe déjà.")
        else:
            now = datetime.utcnow()
            seed = json.loads(json.dumps(DEFAULT_SURVEY))
            for q in seed['questions']:
                for v in q['versions'].values():
                    v['created_at'] = now
            surveys.append(seed)
            db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).set({
                'surveys': surveys,
                'updatedAt': now,
            })
            messages.success(request, "Sondage par défaut créé.")
    except Exception as e:
        logger.error(f"Erreur seed survey: {e}")
        messages.error(request, f"Erreur : {e}")

    return redirect('scripts_manager:survey_list')


@login_required
def survey_results(request, survey_id):
    """Dashboard des résultats d'un sondage (version courante uniquement)."""
    try:
        db = get_firestore_client(request)

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

        responses_docs = db.collection(RESPONSES_COLLECTION)\
            .where('surveyId', '==', survey_id).get()

        responses = []
        for rdoc in responses_docs:
            rdata = rdoc.to_dict()
            rdata['_docId'] = rdoc.id
            responses.append(rdata)

        # Stats par question (version courante)
        question_stats = {}
        for q in survey.get('questions', []):
            qid = q['id']
            current_vid = q.get('current_version_id') or 'v1'
            current_version = (q.get('versions') or {}).get(current_vid, {})
            answers = list(current_version.get('answers') or ['Oui', 'Non'])

            counts = {a: 0 for a in answers}
            total = 0
            for r in responses:
                ans = (r.get('responses') or {}).get(qid)
                ans_str = _legacy_answer_to_string(ans)
                if not ans_str:
                    continue
                v = (r.get('versionMap') or {}).get(qid, 'v1')
                if v != current_vid:
                    continue
                if ans_str in counts:
                    counts[ans_str] += 1
                else:
                    counts[ans_str] = counts.get(ans_str, 0) + 1
                total += 1

            breakdown = []
            for a in answers:
                c = counts.get(a, 0)
                breakdown.append({
                    'answer': a,
                    'count': c,
                    'pct': round(c / total * 100) if total else 0,
                })

            question_stats[qid] = {
                'text': q['text'],
                'current_version_id': current_vid,
                'answers': answers,
                'breakdown': breakdown,
                'total': total,
            }

        restaurant_ids = sorted(set(r.get('restaurantId', '') for r in responses))

        return render(request, 'scripts_manager/surveys/results.html', {
            'survey_json': json.dumps(_serialize_survey_for_json(survey), ensure_ascii=False),
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
def survey_question_history(request, survey_id, qid):
    """Historique des versions d'une question (lecture seule)."""
    try:
        db = get_firestore_client(request)
        doc = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID).get()
        if not doc.exists:
            messages.error(request, "Aucune config sondage.")
            return redirect('scripts_manager:survey_list')

        survey = next((s for s in doc.to_dict().get('surveys', []) if s.get('id') == survey_id), None)
        if not survey:
            messages.error(request, f"Sondage '{survey_id}' introuvable.")
            return redirect('scripts_manager:survey_list')

        question = next((q for q in survey.get('questions', []) if q.get('id') == qid), None)
        if not question:
            messages.error(request, f"Question '{qid}' introuvable.")
            return redirect('scripts_manager:survey_edit', survey_id=survey_id)

        current_vid = question.get('current_version_id') or 'v1'
        versions = question.get('versions') or {}

        # Tri : version courante en haut, puis par created_at desc
        ordered = []
        for vid, vdata in versions.items():
            ordered.append({
                'version_id': vid,
                'is_current': vid == current_vid,
                'answers': list(vdata.get('answers') or []),
                'vote_counts': dict(vdata.get('vote_counts') or {}),
                'created_at': vdata.get('created_at'),
                'archived_at': vdata.get('archived_at'),
                'total_votes': sum(int(v) for v in (vdata.get('vote_counts') or {}).values()),
            })

        def _sort_key(v):
            ca = v.get('created_at')
            if hasattr(ca, 'timestamp'):
                return ca.timestamp()
            return 0

        ordered.sort(key=lambda v: (not v['is_current'], -_sort_key(v)))

        return render(request, 'scripts_manager/surveys/history.html', {
            'survey_id': survey_id,
            'question': {
                'id': question.get('id'),
                'text': question.get('text'),
                'current_version_id': current_vid,
            },
            'versions': ordered,
        })
    except Exception as e:
        logger.error(f"Erreur historique question: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')


@login_required
@require_http_methods(["POST"])
def survey_targeting_count(request):
    """AJAX: nombre de restos qui matchent un bloc de targeting (preview).

    Body JSON :
      { "targeting": { "restaurant_ids": [...] } }
      ou
      { "targeting": { "filters": { "cuisines": [...], ... } } }
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
        targeting = _normalize_targeting(payload.get('targeting'))
        db = get_firestore_client(request)

        if targeting is None:
            # Aucun filtre → tous les restos
            count = sum(1 for _ in db.collection('restaurants').stream())
            return JsonResponse({'count': count, 'mode': 'all'})

        if targeting.get('restaurant_ids'):
            ids = targeting['restaurant_ids']
            count = 0
            for rid in ids:
                if db.collection('restaurants').document(rid).get().exists:
                    count += 1
            return JsonResponse({'count': count, 'mode': 'ids', 'requested': len(ids)})

        filters = targeting.get('filters') or {}
        # Match côté Python : on charge tous les docs et on filtre.
        # AND entre catégories, OR au sein d'une catégorie.
        count = 0
        for doc in db.collection('restaurants').stream():
            data = doc.to_dict() or {}
            ok = True
            for k, wanted in filters.items():
                doc_val = data.get(k)
                if not doc_val:
                    ok = False
                    break
                if isinstance(doc_val, list):
                    if not any(w in doc_val for w in wanted):
                        ok = False
                        break
                else:
                    if doc_val not in wanted:
                        ok = False
                        break
            if ok:
                count += 1
        return JsonResponse({'count': count, 'mode': 'filters'})
    except Exception as e:
        logger.error(f"Erreur targeting count: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def survey_export_csv(request, survey_id):
    """Export CSV des réponses d'un sondage."""
    try:
        db = get_firestore_client(request)

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

        responses_docs = db.collection(RESPONSES_COLLECTION)\
            .where('surveyId', '==', survey_id).get()

        questions = sorted(survey.get('questions', []), key=lambda q: q.get('order', 0))
        q_ids = [q['id'] for q in questions]
        q_texts = {q['id']: q['text'] for q in questions}

        output = StringIO()
        writer = csv.writer(output)

        header = ['userId', 'restaurantId', 'completed', 'completedAt']
        for qid in q_ids:
            header.append(f"{qid} - {q_texts[qid]}")
            header.append(f"{qid}__version")
        writer.writerow(header)

        for rdoc in responses_docs:
            rdata = rdoc.to_dict()
            row = [
                rdata.get('userId', ''),
                rdata.get('restaurantId', ''),
                rdata.get('completed', False),
                str(rdata.get('completedAt', '')),
            ]
            for qid in q_ids:
                ans = (rdata.get('responses') or {}).get(qid)
                row.append(_legacy_answer_to_string(ans) or '')
                row.append((rdata.get('versionMap') or {}).get(qid, ''))
            writer.writerow(row)

        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="survey_{survey_id}_responses.csv"'
        return response

    except Exception as e:
        logger.error(f"Erreur export survey CSV: {e}")
        messages.error(request, f"Erreur : {e}")
        return redirect('scripts_manager:survey_list')
