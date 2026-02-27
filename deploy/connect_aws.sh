#!/bin/bash
# Script pour se connecter au serveur AWS avec Daniel.pem

# Configuration
PEM_FILE="Daniel.pem"
PEM_PATH="$(cd "$(dirname "$0")/.." && pwd)/$PEM_FILE"

# Vérifier que le fichier .pem existe
if [ ! -f "$PEM_PATH" ]; then
    echo "❌ Erreur: Le fichier $PEM_FILE n'existe pas dans $(dirname "$PEM_PATH")"
    exit 1
fi

# Vérifier les permissions
chmod 400 "$PEM_PATH"

# Configuration par défaut du serveur AWS
DEFAULT_SERVER="16.171.225.193"
DEFAULT_USER="ec2-user"

# Demander l'adresse IP ou le nom DNS du serveur
if [ -z "$1" ]; then
    echo "Connexion au serveur AWS par défaut..."
    SERVER_ADDRESS="$DEFAULT_SERVER"
    USER="$DEFAULT_USER"
else
    SERVER_ADDRESS="$1"
    USER="${2:-$DEFAULT_USER}"  # Par défaut: ec2-user (Amazon Linux)
fi

echo "🔐 Connexion au serveur AWS..."
echo "   Serveur: $SERVER_ADDRESS"
echo "   Utilisateur: $USER"
echo "   Clé: $PEM_PATH"
echo ""

# Se connecter
ssh -i "$PEM_PATH" "$USER@$SERVER_ADDRESS"
