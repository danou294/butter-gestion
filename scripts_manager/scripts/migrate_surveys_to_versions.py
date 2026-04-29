#!/usr/bin/env python3
"""
Migration : passe le doc Firestore `survey_config/active` au nouveau schéma de questions
avec versioning + targeting.

Ancien schéma question :
    { id, text, showIf?: {questionId, answer: bool}, order }

Nouveau schéma question :
    {
      id, text, order,
      showIf: { questionId, answer: 'Oui'|'Non'|<string> } | null,
      current_version_id: 'v1',
      versions: { v1: { answers: ['Oui', 'Non'], created_at, vote_counts: {Oui: N, Non: M} } },
      targeting: null,   # tous les restos par défaut
    }

Les compteurs de votes existants (collection `survey_responses`) sont reconstitués pour
la version v1.

Usage :
    python3 migrate_surveys_to_versions.py [--env dev|prod] [--dry-run]

Par défaut : env=dev, dry-run activé. Pour appliquer en dev :
    python3 migrate_surveys_to_versions.py --env dev --apply
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import firebase_admin
from firebase_admin import credentials, firestore

CONFIG_COLLECTION = 'survey_config'
CONFIG_DOC_ID = 'active'
RESPONSES_COLLECTION = 'survey_responses'


def get_service_account_path(env: str) -> str:
    base = Path(__file__).resolve().parent.parent.parent / 'firebase_credentials'
    if env == 'dev':
        return str(base / 'serviceAccountKey.dev.json')
    return str(base / 'serviceAccountKey.prod.json')


def init_firebase(env: str):
    sa_path = get_service_account_path(env)
    if not Path(sa_path).exists():
        print(f"[ERREUR] Service account introuvable : {sa_path}")
        sys.exit(1)
    cred = credentials.Certificate(sa_path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def legacy_answer(value):
    if value is True:
        return 'Oui'
    if value is False:
        return 'Non'
    if isinstance(value, str):
        return value
    return None


def compute_v1_vote_counts(db, survey_id, qid):
    counts = {}
    docs = db.collection(RESPONSES_COLLECTION).where('surveyId', '==', survey_id).stream()
    for d in docs:
        data = d.to_dict() or {}
        ans = (data.get('responses') or {}).get(qid)
        ans_str = legacy_answer(ans)
        if not ans_str:
            continue
        v = (data.get('versionMap') or {}).get(qid, 'v1')
        if v != 'v1':
            continue
        counts[ans_str] = counts.get(ans_str, 0) + 1
    return counts


def needs_migration(question):
    return not (
        isinstance(question.get('versions'), dict)
        and question.get('current_version_id')
    )


def migrate_question(db, survey_id, q, now):
    """Renvoie la version migrée d'une question (sans muter l'originale)."""
    if not needs_migration(q):
        # Garde-fou : assure les champs targeting / showIf normalisés
        out = dict(q)
        out.setdefault('targeting', None)
        showIf = out.get('showIf')
        if isinstance(showIf, dict):
            ans = showIf.get('answer')
            if ans is True:
                showIf = {'questionId': showIf.get('questionId', ''), 'answer': 'Oui'}
            elif ans is False:
                showIf = {'questionId': showIf.get('questionId', ''), 'answer': 'Non'}
            out['showIf'] = showIf
        return out

    qid = q.get('id') or ''
    vote_counts = compute_v1_vote_counts(db, survey_id, qid) if qid else {}
    answers = ['Oui', 'Non']
    # Assure que les clés Oui/Non existent même si zéro vote
    counts = {a: vote_counts.get(a, 0) for a in answers}
    # Si certains votes ont des strings inattendues, on les ajoute
    for k, v in vote_counts.items():
        if k not in counts:
            counts[k] = v

    showIf = q.get('showIf')
    if isinstance(showIf, dict):
        ans = showIf.get('answer')
        if ans is True:
            showIf = {'questionId': showIf.get('questionId', ''), 'answer': 'Oui'}
        elif ans is False:
            showIf = {'questionId': showIf.get('questionId', ''), 'answer': 'Non'}

    return {
        'id': qid,
        'text': q.get('text', ''),
        'order': int(q.get('order') or 0),
        'showIf': showIf if (isinstance(showIf, dict) and showIf.get('questionId')) else None,
        'current_version_id': 'v1',
        'versions': {
            'v1': {
                'answers': answers,
                'created_at': now,
                'vote_counts': counts,
            }
        },
        'targeting': None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', choices=['dev', 'prod'], default='dev')
    parser.add_argument('--apply', action='store_true', help="Applique les changements (sinon dry-run).")
    args = parser.parse_args()

    if args.env == 'prod':
        confirm = input("⚠️  Tu vas migrer sur PROD (butter-vdef). Tape 'PROD' pour confirmer : ")
        if confirm != 'PROD':
            print("Annulé.")
            sys.exit(0)

    print(f"[migrate] env={args.env} apply={args.apply}")
    db = init_firebase(args.env)
    doc_ref = db.collection(CONFIG_COLLECTION).document(CONFIG_DOC_ID)
    doc = doc_ref.get()

    if not doc.exists:
        print("Aucun doc survey_config/active à migrer.")
        return

    data = doc.to_dict() or {}
    surveys = data.get('surveys', []) or []

    if not surveys:
        print("Aucun sondage à migrer.")
        return

    now = datetime.utcnow()
    migrated_count = 0
    new_surveys = []

    for s in surveys:
        new_questions = []
        for q in (s.get('questions') or []):
            mig = migrate_question(db, s.get('id', ''), q, now)
            if mig is not q:
                migrated_count += 1
            new_questions.append(mig)
        new_s = {**s, 'questions': new_questions}
        new_surveys.append(new_s)

    print(f"\n[résumé] {migrated_count} question(s) (re)normalisée(s) sur {sum(len(s.get('questions') or []) for s in surveys)} au total.")

    if not args.apply:
        print("\n[dry-run] Aucune écriture. Aperçu :")
        for s in new_surveys:
            print(f"  - survey {s.get('id')} : {len(s.get('questions') or [])} questions")
            for q in s.get('questions') or []:
                vid = q.get('current_version_id')
                v = (q.get('versions') or {}).get(vid, {})
                print(f"      · {q.get('id')} → {vid} answers={v.get('answers')} counts={v.get('vote_counts')}")
        print("\nLance avec --apply pour écrire.")
        return

    doc_ref.set({
        'surveys': new_surveys,
        'updatedAt': now,
    })
    print("✅ Migration appliquée.")


if __name__ == '__main__':
    main()
