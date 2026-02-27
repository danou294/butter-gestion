# Butter Web Interface — Backend Admin

Interface d'administration Django pour gérer les restaurants, guides, photos, utilisateurs et abonnements de l'app Butter.

## Stack technique

- **Django 4.2** + Firebase Admin SDK
- **Firestore** pour les données metier (pas d'ORM Django)
- **SQLite** uniquement pour le tracking RevenueCat et l'auth Django
- **Tailwind CSS** pour le frontend
- **Firebase Storage** pour les photos/logos

## Structure du projet

```
butter_web_interface/
├── manage.py                          # Django CLI
├── README.md
├── requirements.txt                   # Dependances Python 3.9+
├── requirements-py37.txt              # Dependances Python 3.7 (OVH legacy)
├── package.json / tailwind.config.js  # Frontend (Tailwind CSS)
│
├── deploy/                            # Scripts de deploiement
│   ├── connect_aws.sh                 # Connexion SSH au serveur AWS
│   ├── restart_django_aws.sh          # Redemarrer Django sur AWS (pull + restart)
│   └── start.sh                       # Lancer le serveur en local
│
├── docs/                              # Documentation technique
│   ├── INSTALLATION.md                # Guide d'installation
│   ├── DEPLOIEMENT_OVH.md            # Deploiement sur OVH
│   ├── CONFIGURATION_NGINX_OVH.md    # Config Nginx reverse proxy
│   └── EMPLACEMENT_SERVICE_ACCOUNT.md # Emplacement des service accounts
│
├── data/                              # Fichiers de donnees (gitignored)
│   └── (Excel, CSV, images transmis)
│
├── butter_web_interface/              # Config Django
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── scripts_manager/                   # App principale
│   ├── views.py                       # Orchestrateur (export, import, taches async)
│   ├── restaurants_views.py           # CRUD restaurants
│   ├── photos_views.py               # Gestion photos/logos Firebase Storage
│   ├── users_views.py                # Gestion utilisateurs
│   ├── announcements_views.py        # Annonces et evenements
│   ├── guides_views.py               # Gestion guides thematiques
│   ├── home_guide_views.py           # Guides page d'accueil
│   ├── coups_de_coeur_views.py       # Restaurants mis en avant
│   ├── quick_filters_views.py        # Filtres rapides dynamiques
│   ├── recommended_views.py          # Restaurants recommandes
│   ├── notifications_views.py        # Notifications push FCM
│   ├── revenuecat_views.py           # Dashboard RevenueCat
│   ├── onboarding_views.py           # Gestion onboarding restaurants
│   ├── marrakech_views.py            # Import restaurants Marrakech
│   ├── firebase_env_views.py         # Switch environnement (dev/prod)
│   ├── auth_views.py                 # Auth Django (login/register)
│   ├── import_restaurants.py         # Pipeline import Excel → Firestore
│   ├── config.py                     # Configuration centralisee
│   ├── firebase_utils.py             # Switching environnement Firebase
│   ├── scripts/                      # Scripts standalone (exports, audits, etc.)
│   ├── templates/scripts_manager/    # Templates HTML (Tailwind)
│   └── data/metro_lines.json         # Donnees lignes de metro
│
├── templates/                         # Templates erreur (404, 500)
├── firebase_credentials/              # Service accounts Firebase (gitignored)
├── media/                             # Uploads et exports (gitignored)
├── exports/                           # Exports generes
└── venv/                              # Python virtual env (gitignored)
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

Voir `docs/INSTALLATION.md` pour le guide complet.

## Lancement

```bash
# Avec le script
bash deploy/start.sh

# Manuellement
source venv/bin/activate
python manage.py runserver
```

Interface accessible sur `http://127.0.0.1:8000/`

## Deploiement AWS

```bash
# Deployer sur le serveur AWS (git pull + restart)
bash deploy/restart_django_aws.sh

# Se connecter en SSH au serveur
bash deploy/connect_aws.sh
```

## Import restaurants

1. Preparer un fichier Excel avec les colonnes requises (voir `import_restaurants.py`)
2. Acceder a la page Import dans l'interface
3. Uploader le fichier Excel
4. L'import cree/met a jour les documents Firestore + uploade les photos dans Storage

## Documentation

Voir le dossier `docs/` :
- `INSTALLATION.md` — Guide d'installation complet
- `DEPLOIEMENT_OVH.md` — Deploiement sur serveur OVH
- `CONFIGURATION_NGINX_OVH.md` — Config Nginx reverse proxy
- `EMPLACEMENT_SERVICE_ACCOUNT.md` — Emplacement des service accounts
