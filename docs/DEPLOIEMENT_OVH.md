# 🚀 Guide de déploiement sur OVH

Guide spécifique pour déployer le projet sur un serveur OVH.

## ⚠️ IMPORTANT : Python 3.7 sur OVH

Le serveur OVH a Python 3.7.3, mais Django 4.2 nécessite Python 3.8+. 

**Solution : Utilisez le fichier `requirements-py37.txt` à la place de `requirements.txt`**

### Installation avec Python 3.7

```bash
# 1. Activer l'environnement virtuel
source venv/bin/activate

# 2. Installer les dépendances compatibles Python 3.7
pip install -r requirements-py37.txt

# 3. Vérifier que Django est installé
python -c "import django; print(django.get_version())"

# 4. Continuer avec les étapes normales
python manage.py migrate
python manage.py createsuperuser
```

## 🔌 Problème de port sur OVH

Sur OVH, le port 8000 peut être bloqué. Utilisez un port différent :

```bash
# Essayer le port 8080
python manage.py runserver 0.0.0.0:8080

# Ou le port 8001
python manage.py runserver 0.0.0.0:8001

# Ou le port 3000
python manage.py runserver 0.0.0.0:3000
```

### Ports recommandés pour OVH

- **8080** : Port HTTP alternatif (généralement autorisé)
- **8001, 8002, 8003...** : Ports personnalisés
- **3000, 5000, 9000** : Ports de développement courants

## Problèmes courants et solutions

### 1. Vérifier la version de Python

```bash
python --version
python3 --version
python3.9 --version
python3.10 --version
python3.11 --version
```

**Important** : Le projet nécessite Python 3.9 ou supérieur, mais fonctionne avec Python 3.7 en utilisant `requirements-py37.txt`.

### 2. Créer l'environnement virtuel

Si `venv/bin/activate` n'existe pas, créez l'environnement virtuel :

```bash
# Utiliser python3 explicitement
python3 -m venv venv

# Activer l'environnement
source venv/bin/activate
```

### 3. Vérifier que vous utilisez le bon Python

Après activation de l'environnement virtuel :

```bash
which python
python --version
```

Cela doit pointer vers `venv/bin/python` et afficher Python 3.7+.

### 4. Installation complète sur OVH

```bash
# 1. Aller dans le dossier du projet
cd ~/butter-gestion

# 2. Créer l'environnement virtuel (si pas déjà fait)
python3 -m venv venv

# 3. Activer l'environnement
source venv/bin/activate

# 4. Mettre à jour pip
pip install --upgrade pip

# 5. Installer les dépendances (utiliser requirements-py37.txt pour Python 3.7)
pip install -r requirements-py37.txt

# 6. Vérifier la version de Python
python --version  # Doit être 3.7+

# 7. Créer le dossier input
mkdir -p media/input

# 8. Placer serviceAccountKey.json dans media/input/
# (utilisez scp ou vim pour créer le fichier)

# 9. Initialiser la base de données
python manage.py migrate

# 10. Créer un superutilisateur
python manage.py createsuperuser

# 11. Tester le serveur sur un port autorisé
python manage.py runserver 0.0.0.0:8080
```

## Configuration OVH spécifique

### Si Python 3.9+ n'est pas disponible par défaut

Sur OVH, vous devrez peut-être utiliser un module Python spécifique :

```bash
# Vérifier les modules disponibles
module avail python

# Charger un module Python (exemple)
module load python/3.9
# ou
module load python/3.10
```

### Configuration du serveur web (Nginx/Apache)

Pour la production, configurez un serveur web. Exemple avec Gunicorn :

```bash
# Installer Gunicorn
pip install gunicorn

# Démarrer avec Gunicorn sur un port autorisé
gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:8080 --workers 4
```

### Variables d'environnement

Créez le fichier `.env` :

```bash
nano .env
```

Ajoutez :
```
REVENUECAT_API_KEY=votre_cle_api
```

## Commandes de diagnostic

```bash
# Vérifier Python
python --version
which python

# Vérifier pip
pip --version
which pip

# Vérifier l'environnement virtuel
echo $VIRTUAL_ENV

# Lister les packages installés
pip list

# Vérifier les fichiers essentiels
ls -la media/input/serviceAccountKey.json
ls -la .env
ls -la manage.py

# Tester différents ports
python manage.py runserver 0.0.0.0:8080
python manage.py runserver 0.0.0.0:8001
python manage.py runserver 0.0.0.0:3000
```

## Solution au problème "SyntaxError: invalid syntax"

Cette erreur indique que vous utilisez une version de Python trop ancienne (< 3.3).

**Solution :**

1. Vérifiez la version :
```bash
python --version
```

2. Si c'est Python 2.x ou < 3.7, utilisez python3 :
```bash
python3 --version
python3 manage.py migrate
```

3. Créez l'environnement virtuel avec python3 :
```bash
python3 -m venv venv
source venv/bin/activate
```

4. Vérifiez que vous utilisez le bon Python :
```bash
which python  # Doit afficher .../venv/bin/python
python --version  # Doit être 3.7+
```

## Démarrer en production

### Option 1 : Avec Gunicorn (recommandé)

```bash
source venv/bin/activate
pip install gunicorn
gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:8080 --workers 4 --timeout 120
```

### Option 2 : En arrière-plan avec nohup

```bash
source venv/bin/activate
nohup gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:8080 --workers 4 > gunicorn.log 2>&1 &
```

### Option 3 : Avec screen (pour garder la session)

```bash
screen -S butter
source venv/bin/activate
gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:8080 --workers 4
# Appuyez sur Ctrl+A puis D pour détacher
```

### Option 4 : Avec le serveur de développement Django (test uniquement)

```bash
# Utiliser un port autorisé (pas 8000)
python manage.py runserver 0.0.0.0:8080
```

## Vérification finale

1. ✅ Python 3.7+ installé et utilisé
2. ✅ Environnement virtuel créé et activé
3. ✅ Toutes les dépendances installées
4. ✅ Base de données migrée
5. ✅ Superutilisateur créé
6. ✅ serviceAccountKey.json présent dans media/input/
7. ✅ Serveur démarre sans erreur sur un port autorisé

## Accès à l'interface

Une fois le serveur démarré sur le port 8080 (ou autre), accédez à :

- **Depuis le serveur** : `http://localhost:8080`
- **Depuis l'extérieur** : `http://VOTRE_IP_OVH:8080`

Pour trouver votre IP OVH :
```bash
hostname -I
# ou
ip addr show
```

---

**Besoin d'aide ?** Vérifiez les logs avec `tail -f gunicorn.log` ou les logs Django.
