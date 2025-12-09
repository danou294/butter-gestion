#!/bin/bash
# Script pour redémarrer Django sur le serveur AWS

# Configuration
SERVER_IP="16.171.225.193"
USER="ec2-user"
PEM_FILE="$(cd "$(dirname "$0")" && pwd)/Daniel.pem"
REMOTE_DIR="/home/ec2-user/butter-gestion"  # Nom du repo sur AWS

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🔐 Connexion au serveur AWS...${NC}"
echo -e "   Serveur: $SERVER_IP"
echo ""

# Vérifier que le fichier .pem existe
if [ ! -f "$PEM_FILE" ]; then
    echo "❌ Erreur: Le fichier Daniel.pem n'existe pas"
    exit 1
fi

chmod 400 "$PEM_FILE" 2>/dev/null

# Exécuter les commandes sur le serveur distant
ssh -i "$PEM_FILE" \
    -o StrictHostKeyChecking=no \
    "$USER@$SERVER_IP" << 'ENDSSH'

# Couleurs pour le serveur
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

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

# Trouver le répertoire du projet (chercher dans les emplacements courants)
if [ -d "/home/ec2-user/butter-gestion" ]; then
    PROJECT_DIR="/home/ec2-user/butter-gestion"
elif [ -d "/var/www/butter-gestion" ]; then
    PROJECT_DIR="/var/www/butter-gestion"
elif [ -d "/opt/butter-gestion" ]; then
    PROJECT_DIR="/opt/butter-gestion"
elif [ -d "/home/ec2-user/butter_web_interface" ]; then
    PROJECT_DIR="/home/ec2-user/butter_web_interface"
else
    echo "❌ Répertoire du projet non trouvé. Veuillez spécifier le chemin."
    exit 1
fi

cd "$PROJECT_DIR"
echo -e "${BLUE}📁 Répertoire: $PROJECT_DIR${NC}"
echo ""

echo -e "${BLUE}📥 Mise à jour depuis Git...${NC}"
git pull
echo -e "${GREEN}✅ Git pull terminé${NC}"
echo ""

echo -e "${BLUE}🐍 Activation de l'environnement virtuel...${NC}"
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "env" ]; then
    source env/bin/activate
else
    echo "❌ Environnement virtuel non trouvé (venv ou env)"
    exit 1
fi
echo -e "${GREEN}✅ Environnement virtuel activé${NC}"
echo ""

echo -e "${BLUE}🚀 Lancement du serveur Django sur le port 8000...${NC}"
nohup python manage.py runserver 0.0.0.0:8000 > /tmp/django.log 2>&1 &
sleep 2

# Vérifier que le serveur a démarré
if lsof -ti:8000 > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Serveur Django démarré avec succès${NC}"
    echo -e "   Logs: tail -f /tmp/django.log"
    echo -e "   URL: http://$SERVER_IP:8000"
else
    echo -e "${YELLOW}⚠️  Le serveur semble ne pas avoir démarré. Vérifiez les logs:${NC}"
    echo "   tail -f /tmp/django.log"
fi

ENDSSH

echo ""
echo -e "${GREEN}✅ Opérations terminées sur le serveur${NC}"
