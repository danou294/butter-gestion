#!/bin/bash
# Script de connexion au serveur AWS Butter

# Configuration
SERVER_IP="16.171.225.193"
USER="ec2-user"
PEM_FILE="$(cd "$(dirname "$0")" && pwd)/Daniel.pem"

# Couleurs pour l'affichage
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔐 Connexion au serveur AWS Butter...${NC}"
echo -e "   ${GREEN}Serveur:${NC} $SERVER_IP"
echo -e "   ${GREEN}Utilisateur:${NC} $USER"
echo -e "   ${GREEN}Clé:${NC} $PEM_FILE"
echo ""

# Vérifier que le fichier .pem existe
if [ ! -f "$PEM_FILE" ]; then
    echo "❌ Erreur: Le fichier Daniel.pem n'existe pas dans $(dirname "$PEM_FILE")"
    exit 1
fi

# Vérifier les permissions
chmod 400 "$PEM_FILE" 2>/dev/null

# Se connecter au serveur
ssh -i "$PEM_FILE" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "$USER@$SERVER_IP"
