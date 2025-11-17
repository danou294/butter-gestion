#!/bin/bash
# Script pour lancer le serveur Django avec l'environnement virtuel

cd "$(dirname "$0")"

# Activer l'environnement virtuel
source venv/bin/activate

# Installer les dépendances si nécessaire
if ! python -c "import django" 2>/dev/null; then
    echo "📦 Installation des dépendances..."
    pip install -r requirements.txt
fi

# Lancer le serveur
echo "🚀 Lancement du serveur Django..."
python manage.py runserver


