#!/bin/bash
# Script pour arrêter Django, pull git, activer venv et relancer Django

set -e  # Arrêter en cas d'erreur

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛑 Arrêt du serveur Django...${NC}"

# Arrêter les processus Django sur le port 8000
if lsof -ti:8000 > /dev/null 2>&1; then
    echo -e "${YELLOW}  Arrêt des processus sur le port 8000...${NC}"
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Arrêter les processus manage.py runserver
if pgrep -f "manage.py runserver" > /dev/null; then
    echo -e "${YELLOW}  Arrêt des processus Django...${NC}"
    pkill -f "manage.py runserver" || true
    sleep 1
fi

echo -e "${GREEN}✅ Serveur Django arrêté${NC}"
echo ""

# Aller dans le répertoire du projet
cd "$(dirname "$0")"

echo -e "${BLUE}📥 Mise à jour depuis Git...${NC}"
git pull
echo -e "${GREEN}✅ Git pull terminé${NC}"
echo ""

echo -e "${BLUE}🐍 Activation de l'environnement virtuel...${NC}"
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Le dossier venv n'existe pas${NC}"
    exit 1
fi

source venv/bin/activate
echo -e "${GREEN}✅ Environnement virtuel activé${NC}"
echo ""

echo -e "${BLUE}🚀 Lancement du serveur Django sur le port 8000...${NC}"
python manage.py runserver 8000
