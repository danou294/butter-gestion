#!/usr/bin/env python3
"""
Script pour créer un superutilisateur Django de manière non-interactive
Usage: python3 create_superuser.py
"""
import os
import sys
import django

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'butter_web_interface.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

def create_superuser():
    """Crée un superutilisateur"""
    print("=" * 60)
    print("Création d'un superutilisateur Django")
    print("=" * 60)
    
    # Demander les informations
    username = input("\nNom d'utilisateur: ").strip()
    if not username:
        print("❌ Le nom d'utilisateur est requis")
        return
    
    email = input("Email: ").strip()
    if not email:
        print("❌ L'email est requis")
        return
    
    password = input("Mot de passe: ").strip()
    if not password:
        print("❌ Le mot de passe est requis")
        return
    
    password_confirm = input("Confirmer le mot de passe: ").strip()
    if password != password_confirm:
        print("❌ Les mots de passe ne correspondent pas")
        return
    
    # Vérifier si l'utilisateur existe déjà
    if User.objects.filter(username=username).exists():
        print(f"❌ L'utilisateur '{username}' existe déjà")
        response = input("Voulez-vous le rendre superutilisateur ? (o/n): ").strip().lower()
        if response == 'o':
            user = User.objects.get(username=username)
            user.is_superuser = True
            user.is_staff = True
            user.set_password(password)
            user.save()
            print(f"✅ L'utilisateur '{username}' est maintenant superutilisateur")
        else:
            print("❌ Opération annulée")
        return
    
    if User.objects.filter(email=email).exists():
        print(f"❌ Un utilisateur avec l'email '{email}' existe déjà")
        return
    
    # Créer le superutilisateur
    try:
        User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        print(f"\n✅ Superutilisateur '{username}' créé avec succès !")
        print(f"   Email: {email}")
    except Exception as e:
        print(f"❌ Erreur lors de la création: {e}")

if __name__ == '__main__':
    create_superuser()
