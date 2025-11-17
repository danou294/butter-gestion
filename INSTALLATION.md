# 📦 Guide d'installation rapide

Guide étape par étape pour installer et lancer le projet sur une nouvelle machine.

## Prérequis

- Python 3.9 ou supérieur
- pip (gestionnaire de paquets Python)
- Git (pour cloner le projet)
- Compte Firebase avec fichier `serviceAccountKey.json`

## Installation complète

### Étape 1 : Cloner le projet

```bash
git clone https://github.com/danou294/butter-gestion.git
cd butter-gestion
```

### Étape 2 : Créer l'environnement virtuel

**macOS/Linux :**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows :**
```bash
python -m venv venv
venv\Scripts\activate
```

Vous devriez voir `(venv)` apparaître dans votre terminal.

### Étape 3 : Installer les dépendances

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Cette étape peut prendre quelques minutes.

### Étape 4 : Initialiser la base de données

```bash
python manage.py migrate
```

Cela crée la base de données SQLite et les tables nécessaires.

### Étape 5 : Créer votre compte administrateur

```bash
python manage.py createsuperuser
```

Suivez les instructions :
- **Username** : Choisissez un nom d'utilisateur
- **Email address** : (optionnel)
- **Password** : Créez un mot de passe sécurisé

### Étape 6 : Configurer Firebase

**a) Créer le dossier input :**
```bash
mkdir -p input
```

**b) Placer votre fichier serviceAccountKey.json :**

Copiez votre fichier `serviceAccountKey.json` depuis la console Firebase dans le dossier `input/` :

```bash
# Exemple (remplacez par votre chemin)
cp ~/Downloads/serviceAccountKey.json input/serviceAccountKey.json
```

**Vérification :**
```bash
ls -la input/serviceAccountKey.json
```

### Étape 7 : Configurer RevenueCat (optionnel)

Si vous utilisez RevenueCat pour les abonnements :

```bash
echo "REVENUECAT_API_KEY=votre_cle_api" > .env
```

Remplacez `votre_cle_api` par votre vraie clé API RevenueCat.

### Étape 8 : Démarrer le serveur

```bash
python manage.py runserver
```

Vous devriez voir :
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

### Étape 9 : Accéder à l'interface

1. Ouvrez votre navigateur
2. Allez sur : `http://127.0.0.1:8000/`
3. Vous serez redirigé vers la page de connexion
4. Connectez-vous avec le compte créé à l'étape 5

## Vérification de l'installation

### Vérifier que tout fonctionne

1. ✅ Le serveur démarre sans erreur
2. ✅ La page de connexion s'affiche
3. ✅ Vous pouvez vous connecter
4. ✅ La page d'accueil s'affiche après connexion
5. ✅ Le statut du service account est "✅ Configuré" (si vous avez placé le fichier)

### Problèmes courants

**Erreur : "ModuleNotFoundError"**
```bash
# Réinstaller les dépendances
pip install -r requirements.txt
```

**Erreur : "No module named 'config'"**
```bash
# Vérifier que vous êtes dans le bon répertoire
pwd  # Doit afficher .../butter-gestion
```

**Erreur : "Fichier service account manquant"**
```bash
# Vérifier que le fichier est bien présent
ls -la input/serviceAccountKey.json
```

**Erreur : "Port already in use"**
```bash
# Utiliser un autre port
python manage.py runserver 8001
```

## Accès depuis d'autres machines

Pour rendre l'interface accessible depuis d'autres machines sur le même réseau :

```bash
python manage.py runserver 0.0.0.0:8000
```

Puis accédez depuis une autre machine avec : `http://IP_DE_LA_MACHINE:8000`

Pour trouver l'IP de votre machine :
- **macOS/Linux** : `ifconfig | grep "inet "`
- **Windows** : `ipconfig`

## Commandes utiles

### Arrêter le serveur
Appuyez sur `Ctrl+C` dans le terminal

### Désactiver l'environnement virtuel
```bash
deactivate
```

### Réactiver l'environnement virtuel
```bash
source venv/bin/activate  # macOS/Linux
# ou
venv\Scripts\activate  # Windows
```

### Mettre à jour le projet
```bash
git pull origin main
pip install -r requirements.txt
python manage.py migrate
```

## Prochaines étapes

Une fois l'installation terminée :

1. ✅ Explorez l'interface
2. ✅ Testez les fonctionnalités (Export, Restaurants, Photos, etc.)
3. ✅ Configurez RevenueCat si nécessaire
4. ✅ Créez d'autres comptes utilisateurs via `/register/`

---

**Besoin d'aide ?** Consultez la section [Dépannage](#-dépannage) du README principal.

