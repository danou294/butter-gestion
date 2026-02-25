# Contexte - Module Import Onboarding Restaurants (Django)

## Objectif

Ajouter un module dans `scripts_manager` pour importer et consulter les restaurants d'onboarding dans une collection Firebase **séparée** : `onboarding_restaurants`.

---

## Patterns existants à respecter

### Environnements (dev/prod)

Toujours utiliser le système existant :

```python
# firebase_utils.py
from scripts_manager.firebase_utils import get_service_account_path, get_firebase_env_from_session

# Dans chaque vue :
def my_view(request):
    env = get_firebase_env_from_session(request)  # 'dev' ou 'prod'
    sa_path = get_service_account_path(request)
    # ...
```

**Projets Firebase :**
- Dev : `butter-def` → `serviceAccountKey.dev.json`
- Prod : `butter-vdef` → `serviceAccountKey.prod.json`

**Storage buckets :**
- Dev : `butter-def.firebasestorage.app`
- Prod : `butter-vdef.firebasestorage.app`

### Structure des vues (pattern restaurants_views.py)

```python
# Initialisation Firestore standard
import firebase_admin
from firebase_admin import credentials, firestore

def get_db(request):
    sa = get_service_account_path(request)
    cred = credentials.Certificate(sa)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()
```

### Import Excel (pattern import_restaurants.py)

```python
import pandas as pd

def parse_onboarding_excel(excel_path):
    df = pd.read_excel(excel_path)
    records = []
    for _, row in df.iterrows():
        name = str(row.get('Nom du restaurant', '')).strip()
        tag = str(row.get('Tag', '')).strip()
        lieu = str(row.get('Lieu', '')).strip()
        spec = row.get('Spécialité')
        specialite = str(spec).strip() if pd.notna(spec) else None

        if not tag:
            continue

        records.append({
            'id': tag.upper(),
            'name': name,
            'tag': tag.upper(),
            'lieu': lieu,
            'specialite': specialite,
            'logo_url': None,
            'image_urls': [],
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
        })
    return records
```

---

## Collection Firestore : `onboarding_restaurants`

### Schema d'un document

```json
{
  "id": "BENC",
  "name": "Benchy",
  "tag": "BENC",
  "lieu": "Coffee shop",
  "specialite": null,
  "logo_url": "https://...",
  "image_urls": ["https://...1.webp", "https://...2.webp"],
  "created_at": "2026-02-09T...",
  "updated_at": "2026-02-09T..."
}
```

### Valeurs possibles

| Champ | Valeurs |
|-------|---------|
| `lieu` | `"Restaurant"`, `"Coffee shop"`, `"Bar"` |
| `specialite` | `"Français"`, `"Italien"`, `"Méditerranéen"`, `"Japonais"`, `"Chinois"`, `"Américain"`, `"Indien"`, `"Thaïlandais"`, `null` (pour coffee shops/bars) |

### Storage Firebase

```
Onboarding/
├── Photos/
│   ├── BENC1.webp
│   ├── BENC2.webp
│   └── ...
└── Logos/
    ├── BENC.png
    └── ...
```

---

## Fichiers à créer

### 1. `scripts_manager/onboarding_views.py`

**Vues :**
- `onboarding_list(request)` → Liste tous les restaurants onboarding
- `onboarding_detail(request, restaurant_id)` → Détail d'un restaurant
- `onboarding_import(request)` → Page d'upload Excel
- `onboarding_import_confirm(request)` → Preview + confirmation

### 2. `scripts_manager/import_onboarding.py`

**Pipeline (simplifié vs restaurants) :**
1. Parse Excel (4 colonnes)
2. Valide les données (tag unique, lieu valide)
3. Preview des changements
4. Import dans Firestore collection `onboarding_restaurants`
5. Log de l'opération

### 3. Templates

```
templates/scripts_manager/onboarding/
├── list.html        # Tableau avec nom, tag, lieu, spécialité, photo status
├── detail.html      # Détail + upload photos/logo
└── import.html      # Upload Excel + preview + confirm
```

S'inspirer de `restaurants/list.html` et `restaurants/detail.html` pour le style.

### 4. Routes (dans `urls.py`)

```python
# Onboarding restaurants
path('onboarding-restaurants/', views.onboarding_list, name='onboarding_list'),
path('onboarding-restaurants/<str:restaurant_id>/', views.onboarding_detail, name='onboarding_detail'),
path('onboarding-restaurants/import/', views.onboarding_import, name='onboarding_import'),
path('onboarding-restaurants/import/confirm/', views.onboarding_import_confirm, name='onboarding_import_confirm'),
```

---

## Données Excel (34 entrées)

### Coffee shops (4)
| Nom | Tag | Lieu |
|-----|-----|------|
| Benchy | BENC | Coffee shop |
| City of light | CITY | Coffee shop |
| Dancing goat | DANC | Coffee shop |
| Mini cafe | MINI | Coffee shop |

### Bars (5)
| Nom | Tag | Lieu |
|-----|-----|------|
| Candeleira | CAND | Bar |
| cravan | CRAV | Bar |
| le tres particulier | LETR | Bar |
| Patate douce | PATA | Bar |
| Le serpent a plume | LESE | Bar |

### Restaurants (25) - par spécialité
| Spécialité | Count | Exemples |
|-----------|-------|----------|
| Français | 5 | Alfred, Arcane 17, Fontaine gaillon... |
| Méditerranéen | 6 | Amagat, daimant, casa preconda... |
| Italien | 5 | (voir Excel) |
| Américain | 3 | (voir Excel) |
| Japonais | 3 | (voir Excel) |
| Thaïlandais | 1 | (voir Excel) |
| Chinois | 1 | (voir Excel) |
| Indien | 1 | (voir Excel) |
