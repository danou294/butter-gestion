#!/usr/bin/env python3
"""
Script to query ALL restaurants from Firestore and extract restriction/preference values.
Checks both dev (butter-def) and prod (butter-vdef) environments.
Uses the service account keys from the Django project's firebase_credentials directory.
"""

import os
import sys
import json
from collections import Counter
from pathlib import Path

# Add the project to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import firebase_admin
from firebase_admin import credentials, firestore


def analyze_environment(env_name, service_account_path):
    """Analyze restriction/preference fields for one Firebase environment."""

    print(f"\n{'='*70}")
    print(f"  ENVIRONMENT: {env_name.upper()}")
    print(f"  Service account: {service_account_path}")
    print(f"{'='*70}")

    if not os.path.exists(service_account_path):
        print(f"  ERROR: Service account file not found: {service_account_path}")
        return

    # Initialize Firebase app with a unique name per environment
    app_name = f"check_restrictions_{env_name}"
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        cred = credentials.Certificate(service_account_path)
        app = firebase_admin.initialize_app(cred, name=app_name)

    db = firestore.client(app=app)

    # Query ALL restaurants
    print(f"\n  Fetching all restaurants from Firestore...")
    restaurants_ref = db.collection('restaurants')
    docs = restaurants_ref.stream()

    total_count = 0

    # Counters for each field
    restrictions_counter = Counter()     # 'restrictions' field
    preferences_counter = Counter()      # 'preferences' field
    preferences_tag_counter = Counter()  # 'preferences_tag' field
    diet_counter = Counter()             # 'diet' field (if exists)

    # Track which restaurants have which fields
    has_restrictions = 0
    has_preferences = 0
    has_preferences_tag = 0
    has_diet = 0

    # Track restaurants with non-empty values
    restaurants_with_restrictions = []
    restaurants_with_preferences = []
    restaurants_with_preferences_tag = []

    for doc in docs:
        total_count += 1
        data = doc.to_dict()
        name = data.get('name', data.get('tag', doc.id))

        # Check 'restrictions' field
        restrictions = data.get('restrictions', None)
        if restrictions is not None:
            has_restrictions += 1
            if isinstance(restrictions, list) and len(restrictions) > 0:
                restaurants_with_restrictions.append(name)
                for r in restrictions:
                    restrictions_counter[str(r)] += 1
            elif isinstance(restrictions, str) and restrictions.strip():
                restaurants_with_restrictions.append(name)
                for r in restrictions.split(','):
                    r = r.strip()
                    if r:
                        restrictions_counter[r] += 1

        # Check 'preferences' field
        preferences = data.get('preferences', None)
        if preferences is None:
            # Also check with accent
            preferences = data.get('préférences', None)
        if preferences is not None:
            has_preferences += 1
            if isinstance(preferences, list) and len(preferences) > 0:
                restaurants_with_preferences.append(name)
                for p in preferences:
                    preferences_counter[str(p)] += 1
            elif isinstance(preferences, str) and preferences.strip():
                restaurants_with_preferences.append(name)
                for p in preferences.split(','):
                    p = p.strip()
                    if p:
                        preferences_counter[p] += 1

        # Check 'preferences_tag' field
        preferences_tag = data.get('preferences_tag', None)
        if preferences_tag is not None:
            has_preferences_tag += 1
            if isinstance(preferences_tag, list) and len(preferences_tag) > 0:
                restaurants_with_preferences_tag.append(name)
                for pt in preferences_tag:
                    preferences_tag_counter[str(pt)] += 1
            elif isinstance(preferences_tag, str) and preferences_tag.strip():
                restaurants_with_preferences_tag.append(name)
                for pt in preferences_tag.split(','):
                    pt = pt.strip()
                    if pt:
                        preferences_tag_counter[pt] += 1

        # Check 'diet' field
        diet = data.get('diet', None)
        if diet is not None:
            has_diet += 1
            if isinstance(diet, list) and len(diet) > 0:
                for d in diet:
                    diet_counter[str(d)] += 1
            elif isinstance(diet, str) and diet.strip():
                for d in diet.split(','):
                    d = d.strip()
                    if d:
                        diet_counter[d] += 1

    print(f"\n  Total restaurants: {total_count}")

    # Print results for each field
    print(f"\n  --- Field: 'restrictions' ---")
    print(f"  Documents with field present: {has_restrictions}/{total_count}")
    print(f"  Documents with non-empty values: {len(restaurants_with_restrictions)}")
    if restrictions_counter:
        print(f"  Unique values ({len(restrictions_counter)}):")
        for value, count in restrictions_counter.most_common():
            print(f"    - '{value}': {count} restaurants")
        if len(restaurants_with_restrictions) <= 20:
            print(f"  Restaurants: {restaurants_with_restrictions}")
    else:
        print(f"  No non-empty values found.")

    print(f"\n  --- Field: 'preferences' (or 'préférences') ---")
    print(f"  Documents with field present: {has_preferences}/{total_count}")
    print(f"  Documents with non-empty values: {len(restaurants_with_preferences)}")
    if preferences_counter:
        print(f"  Unique values ({len(preferences_counter)}):")
        for value, count in preferences_counter.most_common():
            print(f"    - '{value}': {count} restaurants")
    else:
        print(f"  No non-empty values found.")

    print(f"\n  --- Field: 'preferences_tag' ---")
    print(f"  Documents with field present: {has_preferences_tag}/{total_count}")
    print(f"  Documents with non-empty values: {len(restaurants_with_preferences_tag)}")
    if preferences_tag_counter:
        print(f"  Unique values ({len(preferences_tag_counter)}):")
        for value, count in preferences_tag_counter.most_common():
            print(f"    - '{value}': {count} restaurants")
    else:
        print(f"  No non-empty values found.")

    print(f"\n  --- Field: 'diet' ---")
    print(f"  Documents with field present: {has_diet}/{total_count}")
    if diet_counter:
        print(f"  Unique values ({len(diet_counter)}):")
        for value, count in diet_counter.most_common():
            print(f"    - '{value}': {count} restaurants")
    else:
        print(f"  No non-empty values found.")

    # Summary
    print(f"\n  --- SUMMARY ---")
    print(f"  The Firestore field used for search filtering is 'preferences_tag'")
    print(f"  (queried via arrayContainsAny in the Flutter search_service.dart)")
    print(f"  Total restaurants with any restriction/preference value: "
          f"{len(set(restaurants_with_restrictions + restaurants_with_preferences + restaurants_with_preferences_tag))}")


if __name__ == "__main__":
    CREDENTIALS_DIR = Path(__file__).resolve().parent / "firebase_credentials"

    dev_key = CREDENTIALS_DIR / "serviceAccountKey.dev.json"
    prod_key = CREDENTIALS_DIR / "serviceAccountKey.prod.json"

    print("=" * 70)
    print("  BUTTER - Firestore Restriction/Preference Values Analysis")
    print("=" * 70)

    # Check dev environment
    if dev_key.exists():
        analyze_environment("dev (butter-def)", str(dev_key))
    else:
        print(f"\n  SKIP: Dev service account not found at {dev_key}")

    # Check prod environment
    if prod_key.exists():
        analyze_environment("prod (butter-vdef)", str(prod_key))
    else:
        print(f"\n  SKIP: Prod service account not found at {prod_key}")

    print(f"\n{'='*70}")
    print("  DONE")
    print(f"{'='*70}")
