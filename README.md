# 🧈 Butter - Interface de Gestion Firebase

Interface web moderne et complète pour gérer votre application Firebase, incluant la gestion des utilisateurs, restaurants, photos, notifications push et exports de données.

## 📋 Table des matières

- [Fonctionnalités](#-fonctionnalités)
- [Technologies utilisées](#-technologies-utilisées)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Utilisation](#-utilisation)
- [Structure du projet](#-structure-du-projet)
- [Authentification](#-authentification)
- [Dépannage](#-dépannage)

## ✨ Fonctionnalités

### 🔐 Authentification
- **Inscription** : Création de compte utilisateur
- **Connexion/Déconnexion** : Gestion de session sécurisée
- **Protection des pages** : Toutes les fonctionnalités nécessitent une authentification

### 👥 Gestion des Utilisateurs
- **Liste complète** : Affichage de tous les utilisateurs Firebase Auth et Firestore
- **Recherche** : Recherche par nom, email ou téléphone
- **Filtres** : Filtrage par statut (Premium, Trial, Grace period, Expiré, Gratuit)
- **Intégration RevenueCat** : Affichage du statut d'abonnement en temps réel
- **Indicateur de connexion** : Visualisation des utilisateurs en ligne
- **Tokens FCM** : Affichage des tokens de notification push
- **Pagination** : Navigation efficace pour de grandes listes

### 🍽️ Gestion des Restaurants
- **CRUD complet** : Création, lecture, mise à jour et suppression
- **Recherche avancée** : Recherche approximative (fuzzy search) par nom
- **Filtres intelligents** : Filtrage par photos/logos manquants
- **Informations média** : Affichage du nombre de photos et logos par restaurant
- **Import batch** : Import en masse depuis un fichier Excel
- **Pagination** : Gestion efficace de grandes listes

### 📸 Gestion des Photos
- **Gestion des logos** : Upload, suppression, renommage dans le dossier `Logos/`
- **Gestion des photos** : Upload, suppression, renommage dans `Photos restaurants/`
- **Optimisation automatique** : Conversion PNG → WebP avec compression
- **Actions groupées** : Suppression en masse de photos sélectionnées
- **Recherche** : Recherche par nom de fichier
- **Lazy loading** : Chargement à la demande des URLs signées

### 📱 Notifications Push
- **Envoi à tous** : Notification globale à tous les utilisateurs
- **Notifications personnalisées** : Personnalisation avec le prénom de l'utilisateur
- **Envoi par groupe** : Sélection d'utilisateurs spécifiques
- **Intégration FCM** : Utilisation de Firebase Cloud Messaging

### 📤 Exports
- **Export Firestore** : Export des collections (users, restaurants, recommandations, feedbacks)
- **Export Firebase Auth** : Export des utilisateurs d'authentification
- **Format Excel** : Téléchargement direct des fichiers `.xlsx`
- **Collections supportées** : users, restaurants, recommandations, feedbacks

## 🛠️ Technologies utilisées

### Backend
- **Django 4.x** : Framework web Python
- **Firebase Admin SDK** : Gestion Firebase (Auth, Firestore, Storage)
- **Google Cloud Storage** : Gestion des fichiers
- **RevenueCat API** : Intégration des abonnements
- **Pillow (PIL)** : Traitement d'images
- **pandas** : Manipulation de données Excel

### Frontend
- **Tailwind CSS** : Framework CSS utility-first
- **JavaScript (Vanilla)** : Interactivité côté client
- **Google Fonts (Inria)** : Typographie moderne

### Infrastructure
- **Firebase Firestore** : Base de données NoSQL
- **Firebase Authentication** : Authentification utilisateurs
- **Firebase Storage** : Stockage de fichiers
- **Firebase Cloud Messaging** : Notifications push

## 📦 Prérequis

- Python 3.9 ou supérieur
- pip (gestionnaire de paquets Python)
- Compte Firebase avec projet configuré
- Fichier `serviceAccountKey.json` de Firebase
- (Optionnel) Clé API RevenueCat pour les fonctionnalités premium

## 🚀 Installation

### 1. Cloner le projet

```bash
cd /Users/admin/Documents/butter_web_interface
```

### 2. Créer un environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate  # Sur macOS/Linux
# ou
venv\Scripts\activate  # Sur Windows
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 4. Configurer la base de données

```bash
python manage.py migrate
```

### 5. Créer un superutilisateur (optionnel)

```bash
python manage.py createsuperuser
```

## ⚙️ Configuration

### 1. Fichier serviceAccountKey.json

Placez votre fichier `serviceAccountKey.json` de Firebase dans le dossier `input/` :

```bash
cp /chemin/vers/votre/serviceAccountKey.json input/serviceAccountKey.json
```

### 2. Variables d'environnement (optionnel)

Créez un fichier `.env` à la racine du projet pour la clé API RevenueCat :

```env
REVENUECAT_API_KEY=votre_cle_api_revenuecat
```

### 3. Configuration Django

Les paramètres principaux sont dans `butter_web_interface/settings.py`. Les chemins par défaut sont :

- **Service Account** : `input/serviceAccountKey.json`
- **Exports** : `media/exports/`
- **Input** : `media/input/`

## 🎯 Utilisation

### Démarrer le serveur de développement

```bash
python manage.py runserver
```

L'interface sera accessible à l'adresse : `http://127.0.0.1:8000/`

### Première connexion

1. Accédez à `http://127.0.0.1:8000/register/`
2. Créez un compte avec un nom d'utilisateur et un mot de passe
3. Vous serez automatiquement connecté et redirigé vers la page d'accueil

### Utilisation des fonctionnalités

#### 👥 Gestion des Utilisateurs
- Accédez à **"👥 Utilisateurs"** dans le menu
- Utilisez la barre de recherche pour trouver un utilisateur
- Filtrez par statut RevenueCat (Premium, Trial, etc.)
- Cliquez sur **"🔄 Actualiser"** pour mettre à jour le statut d'un utilisateur

#### 🍽️ Gestion des Restaurants
- Accédez à **"Restaurants"** dans le menu
- Cliquez sur **"➕ Nouveau Restaurant"** pour créer un restaurant
- Utilisez les filtres **"📸 Photos manquantes"** ou **"🖼️ Logos manquants"**
- Recherchez par nom avec la recherche approximative
- Importez en masse via **"📥 Import"**

#### 📸 Gestion des Photos
- Accédez à **"📸 Photos"** dans le menu
- Sélectionnez le dossier (**Logos** ou **Photos restaurants**)
- Cliquez sur **"➕ Upload Photo"** pour téléverser une image
- Utilisez **"🔄 Convertir PNG → WebP"** pour optimiser les photos (Photos restaurants uniquement)
- Sélectionnez plusieurs photos pour des actions groupées

#### 📱 Notifications Push
- Accédez à **"📱 Notifications"** dans le menu
- Choisissez le type d'envoi :
  - **📢 À tous** : Notification globale
  - **👤 Personnalisées** : Avec le prénom (utilisez `{prenom}` dans le texte)
  - **👥 Groupe** : Sélection d'utilisateurs spécifiques
- Remplissez le titre et le message
- Envoyez la notification

#### 📤 Exports
- Accédez à **"Export"** dans le menu
- Sélectionnez le type d'export :
  - **Collection Firestore** : Choisissez la collection (users, restaurants, etc.)
  - **Utilisateurs Firebase Auth** : Export des utilisateurs d'authentification
- Cliquez sur **"🚀 Exporter"**
- Le fichier Excel sera téléchargé automatiquement

## 📁 Structure du projet

```
butter_web_interface/
├── butter_web_interface/          # Configuration Django
│   ├── settings.py               # Paramètres du projet
│   ├── urls.py                   # URLs principales
│   └── wsgi.py                   # Configuration WSGI
│
├── scripts_manager/               # Application principale
│   ├── auth_views.py             # Vues d'authentification
│   ├── views.py                  # Vues principales (export, import)
│   ├── restaurants_views.py      # CRUD restaurants
│   ├── photos_views.py           # CRUD photos
│   ├── users_views.py            # Gestion utilisateurs
│   ├── notifications_views.py    # Notifications push
│   ├── notifications_services.py # Services de notification
│   ├── import_restaurants.py    # Script d'import batch
│   ├── config.py                 # Configuration des chemins
│   │
│   ├── templates/                # Templates HTML
│   │   └── scripts_manager/
│   │       ├── base.html         # Template de base
│   │       ├── index.html        # Page d'accueil
│   │       ├── export.html       # Page d'export
│   │       ├── auth/             # Pages d'authentification
│   │       ├── restaurants/      # Pages restaurants
│   │       ├── photos/           # Pages photos
│   │       ├── users/            # Pages utilisateurs
│   │       └── notifications/    # Pages notifications
│   │
│   └── scripts/                  # Scripts Python
│       └── export_to_excel.py   # Script d'export Excel
│
├── input/                        # Fichiers d'entrée
│   └── serviceAccountKey.json   # Clés Firebase (à ajouter)
│
├── media/                        # Fichiers média (générés)
│   ├── exports/                 # Fichiers Excel exportés
│   └── input/                   # Fichiers uploadés
│
├── venv/                         # Environnement virtuel (ignoré)
├── .env                          # Variables d'environnement (optionnel)
├── requirements.txt              # Dépendances Python
└── README.md                     # Ce fichier
```

## 🔐 Authentification

### Création de compte

1. Accédez à `/register/`
2. Remplissez le formulaire :
   - **Nom d'utilisateur** : 150 caractères max, lettres, chiffres et @/./+/-/_ uniquement
   - **Mot de passe** : Minimum 8 caractères, ne peut pas être entièrement numérique
   - **Confirmation** : Doit correspondre au mot de passe
3. Cliquez sur **"✨ Créer mon compte"**
4. Vous serez automatiquement connecté

### Connexion

1. Accédez à `/login/`
2. Entrez votre nom d'utilisateur et mot de passe
3. Cliquez sur **"🔓 Se connecter"**
4. Vous serez redirigé vers la page d'accueil

### Déconnexion

Cliquez sur **"🚪 Déconnexion"** dans le menu de navigation.

## 🎨 Design

L'interface utilise un design moderne avec :

- **Palette de couleurs** :
  - `#111111` - Texte principal
  - `#535353` - Texte secondaire
  - `#FFFFFF` - Fond blanc
  - `#F1EFEB` - Fond beige clair
  - `#C9C1B1` - Beige foncé
  - `#60BC81` - Vert (actions positives)
  - `#D3695E` - Rouge (actions de suppression)

- **Typographie** :
  - **Inria Sans** : Texte principal
  - **Inria Serif** : Titres

- **Boutons** :
  - Border-radius : 14px minimum
  - Padding : 14px 28px
  - Texte blanc sur boutons colorés

## 🔧 Dépannage

### Erreur : "Fichier service account manquant"

**Solution** : Placez votre fichier `serviceAccountKey.json` dans le dossier `input/`

### Erreur : "ModuleNotFoundError"

**Solution** : 
```bash
pip install -r requirements.txt
```

### Erreur : "No module named 'config'"

**Solution** : Vérifiez que le fichier `scripts_manager/config.py` existe et contient les bonnes configurations.

### Erreur : "ExpiredToken" pour les photos

**Solution** : Les URLs signées sont générées à la demande. Si l'erreur persiste, rechargez la page.

### Les utilisateurs RevenueCat ne s'affichent pas

**Solution** : 
1. Vérifiez que la clé API RevenueCat est dans le fichier `.env`
2. Vérifiez que les numéros de téléphone dans Firebase correspondent aux `appUserID` dans RevenueCat (hash SHA256)

### Le serveur ne démarre pas

**Solution** :
```bash
# Vérifiez que vous êtes dans l'environnement virtuel
source venv/bin/activate

# Vérifiez les migrations
python manage.py migrate

# Redémarrez le serveur
python manage.py runserver
```

## 📝 Notes importantes

- **Sécurité** : En production, changez le `SECRET_KEY` dans `settings.py` et activez `DEBUG = False`
- **Base de données** : Le projet utilise SQLite par défaut. Pour la production, configurez PostgreSQL ou MySQL
- **Fichiers sensibles** : Ne commitez jamais `serviceAccountKey.json` ou `.env` dans Git
- **Performance** : Le système utilise le cache Django pour optimiser les performances (cache en mémoire)

## 🤝 Contribution

Ce projet est un outil interne de gestion. Pour toute question ou problème, contactez l'équipe de développement.

## 📄 Licence

Propriétaire - Tous droits réservés

---

**Développé avec ❤️ pour Butter**
