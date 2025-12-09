#!/bin/bash
# Script pour se connecter au serveur AWS avec Daniel.pem

# Configuration
PEM_FILE="Daniel.pem"
PEM_PATH="$(cd "$(dirname "$0")" && pwd)/$PEM_FILE"

# Vérifier que le fichier .pem existe
if [ ! -f "$PEM_PATH" ]; then
    echo "❌ Erreur: Le fichier $PEM_FILE n'existe pas dans $(dirname "$PEM_PATH")"
    exit 1
fi

# Vérifier les permissions
chmod 400 "$PEM_PATH"

# Demander l'adresse IP ou le nom DNS du serveur
if [ -z "$1" ]; then
    echo "Usage: ./connect_aws.sh <adresse_ip_ou_dns> [utilisateur]"
    echo ""
    echo "Exemples:"
    echo "  ./connect_aws.sh ec2-12-34-56-78.compute-1.amazonaws.com"
    echo "  ./connect_aws.sh 12.34.56.78"
    echo "  ./connect_aws.sh 12.34.56.78 ubuntu"
    echo ""
    echo "Utilisateurs par défaut selon l'AMI:"
    echo "  - Amazon Linux: ec2-user"
    echo "  - Ubuntu: ubuntu"
    echo "  - Debian: admin"
    echo "  - CentOS: centos"
    exit 1
fi

SERVER_ADDRESS="$1"
USER="${2:-ec2-user}"  # Par défaut: ec2-user (Amazon Linux)

echo "🔐 Connexion au serveur AWS..."
echo "   Serveur: $SERVER_ADDRESS"
echo "   Utilisateur: $USER"
echo "   Clé: $PEM_PATH"
echo ""

# Se connecter
ssh -i "$PEM_PATH" "$USER@$SERVER_ADDRESS"
