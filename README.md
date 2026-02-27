# Butter Web Interface — Backend Admin

Interface d'administration Django pour gérer les restaurants, guides, photos, utilisateurs et abonnements de l'app Butter.

## Stack technique

- **Django 4.2** + Firebase Admin SDK
- **Firestore** pour les données metier (pas d'ORM Django)
- **SQLite** uniquement pour le tracking RevenueCat et l'auth Django
- **Tailwind CSS** pour le frontend
- **Firebase Storage** pour les photos/logos

## Architecture

```
butter_web_interface/
├── butter_web_interface/              # Config Django
│   ├── settings.py                    # Parametres projet
│   ├── urls.py                        # URLs racine
│   └── wsgi.py                        # WSGI
│
├── scripts_manager/                   # App principale
│   ├── views.py                       # Orchestrateur (export, import, taches async)
│   ├── restaurants_views.py           # CRUD restaurants
│   ├── photos_views.py               # Gestion photos/logos Firebase Storage
│   ├── users_views.py                # Gestion utilisateurs Firebase Auth + Firestore
│   ├── announcements_views.py        # Annonces et evenements
│   ├── guides_views.py               # Gestion guides thematiques
│   ├── home_guide_views.py           # Guides de la page d'accueil
│   ├── coups_de_coeur_views.py       # Restaurants mis en avant
│   ├── quick_filters_views.py        # Filtres rapides dynamiques
│   ├── recommended_views.py          # Restaurants recommandes
│   ├── notifications_views.py        # Notifications push FCM
│   ├── notifications_services.py     # Services de notification
│   ├── signups_views.py              # Stats inscriptions
│   ├── search_restaurants_views.py   # Recherche restaurants (web)
│   ├── search_restaurants_script.py  # Logique recherche
│   ├── revenuecat_views.py           # Dashboard RevenueCat
│   ├── revenuecat_service.py         # Service RevenueCat API
│   ├── onboarding_views.py           # Gestion onboarding restaurants
│   ├── marrakech_views.py            # Import restaurants Marrakech
│   ├── firebase_env_views.py         # Switch d'environnement (dev/prod)
│   ├── auth_views.py                 # Auth Django (login/register)
│   │
│   ├── import_restaurants.py         # Pipeline import Excel → Firestore
│   ├── import_onboarding.py          # Import onboarding restaurants
│   ├── restore_backup.py             # Restauration backup Firestore
│   │
│   ├── config.py                     # Configuration centralisee (chemins, buckets, env)
│   ├── firebase_utils.py             # Switching environnement Firebase via session Django
│   ├── context_processors.py         # Context processors (env label dans templates)
│   ├── models.py                     # Modeles Django (RevenueCat tracking)
│   ├── urls.py                       # URLs de l'app
│   │
│   ├── templates/scripts_manager/    # Templates HTML (Tailwind)
│   │   ├── base.html                 # Layout de base
│   │   ├── index.html                # Page d'accueil
│   │   ├── auth/                     # Login, register
│   │   ├── restaurants/              # Liste, form, detail
│   │   ├── photos/                   # Gestion photos
│   │   ├── users/                    # Liste utilisateurs
│   │   ├── notifications/            # Envoi notifications
│   │   ├── guides/                   # Gestion guides
│   │   ├── announcements/            # Gestion annonces
│   │   └── marrakech/                # Import Marrakech
│   │
│   ├── scripts/                      # Scripts standalone
│   │   ├── export_to_excel.py        # Export collections → Excel
│   │   ├── export_premium_users.py   # Export utilisateurs premium
│   │   ├── export_user_phones.py     # Export telephones
│   │   ├── export_users_top_favoris.py  # Export top favoris
│   │   ├── signups_by_date.py        # Stats inscriptions par date
│   │   ├── sync_revenuecat_attributes.py  # Sync attributs RevenueCat
│   │   ├── check_missing_photos.py   # Audit photos manquantes
│   │   ├── check_missing_logos.py    # Audit logos manquants
│   │   ├── optimize_firebase_images.py  # Optimisation images Storage
│   │   ├── convert_local_images.py   # Conversion images locales
│   │   ├── update_photo_count.py     # MAJ compteur photos
│   │   ├── add_city_field.py         # Ajout champ city aux restaurants
│   │   └── export-bdd-butter.py      # Export complet BDD
│   │
│   └── data/
│       └── metro_lines.json          # Donnees lignes de metro
│
├── firebase_credentials/              # Service accounts Firebase (gitignore)
│   ├── serviceAccountKey.dev.json
│   └── serviceAccountKey.prod.json
│
├── media/                             # Fichiers generes
│   ├── exports/                       # Exports Excel
│   └── input/                         # Fichiers uploades (Excel import)
│
├── .env                               # Variables d'env (REVENUECAT_API_KEY)
├── requirements.txt                   # Dependances Python
├── manage.py                          # Django CLI
└── start.sh                           # Script demarrage
```

## Environnements Firebase

Le switching d'environnement se fait via la **session Django** :

| Env | Project ID | Bucket Storage |
|-----|------------|----------------|
| Dev | `butter-def` | `butter-def.firebasestorage.app` |
| Prod | `butter-vdef` | `butter-vdef.firebasestorage.app` |

- `firebase_utils.py` → `get_firebase_env_from_session(request)` retourne `'dev'` ou `'prod'`
- Le toggle est accessible dans l'interface web (header)
- Les photos Storage utilisent toujours le bucket prod dans l'app Flutter

## Collections Firestore gerees

| Collection | Operations |
|------------|------------|
| `restaurants` | CRUD complet, import Excel, recherche |
| `guides` | CRUD, association restaurants |
| `announcements` | CRUD evenements/sondages |
| `users` | Lecture, recherche, stats |
| `favorites` | Lecture (stats) |
| `user_preferences` | Lecture (onboarding) |
| `quick_filters` | CRUD filtres dynamiques |
| `onboarding_restaurants` | Import, gestion |
| `coups_de_coeur` | CRUD restaurants mis en avant |

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

### Fichiers requis

1. **Service accounts Firebase** dans `firebase_credentials/` :
   - `serviceAccountKey.dev.json` (projet `butter-def`)
   - `serviceAccountKey.prod.json` (projet `butter-vdef`)

2. **Variables d'environnement** (`.env`) :
   ```
   REVENUECAT_API_KEY=sk_...
   ```

## Lancement

```bash
source venv/bin/activate
python manage.py runserver
```

Interface accessible sur `http://127.0.0.1:8000/`

## Import restaurants

1. Preparer un fichier Excel avec les colonnes requises (voir `import_restaurants.py`)
2. Acceder a la page Import dans l'interface
3. Uploader le fichier Excel
4. L'import cree/met a jour les documents Firestore + uploade les photos dans Storage

## Docs de deploiement

- `INSTALLATION.md` — Guide d'installation complet
- `CONFIGURATION_NGINX_OVH.md` — Config Nginx sur OVH
- `DEPLOIEMENT_OVH.md` — Deploiement sur serveur OVH
- `EMPLACEMENT_SERVICE_ACCOUNT.md` — Ou placer les service accounts
