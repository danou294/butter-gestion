#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script adapté pour Django : Recherche de restaurants via Google Places API
"""

import os
import sys
import json
import time
import math
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import unicodedata
from urllib.parse import urljoin, urlparse

try:
    import googlemaps
    GOOGLEMAPS_AVAILABLE = True
except ImportError:
    GOOGLEMAPS_AVAILABLE = False

try:
    import requests
    from bs4 import BeautifulSoup
    SCRAPING_AVAILABLE = True
except ImportError as e:
    SCRAPING_AVAILABLE = False
    # Logger l'erreur pour debug
    import sys
    import traceback
    print(f"⚠️  Modules de scraping non disponibles: {e}", file=sys.stderr)
    print(f"   Traceback: {traceback.format_exc()}", file=sys.stderr)

import pandas as pd


def log(msg: str, log_file: str):
    """Écrit un message dans le log et l'affiche"""
    print(msg)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as e:
        print(f"Erreur écriture log: {e}")


def extract_cid_from_google_url(url):
    """Extrait le CID depuis une URL Google Maps"""
    if not url:
        return None
    match = re.search(r'cid=(\d+)', url)
    if match:
        return match.group(1)
    return None


def normalize_query(query):
    """Normalise une requête pour la recherche (enlève accents, normalise)"""
    if not query:
        return query
    
    # Enlever les accents
    s = unicodedata.normalize('NFD', query.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Normaliser les espaces
    s = ' '.join(s.split())
    return s


def generate_search_variants(restaurant_name):
    """Génère plusieurs variantes de recherche pour un nom de restaurant"""
    variants = []
    
    # Nom original
    variants.append(restaurant_name)
    
    # Nom sans accents
    variants.append(normalize_query(restaurant_name))
    
    # Avec "restaurant" devant
    variants.append(f"restaurant {restaurant_name}")
    variants.append(f"restaurant {normalize_query(restaurant_name)}")
    
    # Avec "restaurant" derrière
    variants.append(f"{restaurant_name} restaurant")
    variants.append(f"{normalize_query(restaurant_name)} restaurant")
    
    # Avec "Paris"
    variants.append(f"{restaurant_name} Paris")
    variants.append(f"{normalize_query(restaurant_name)} Paris")
    
    # Enlever les mots communs et réessayer
    words = restaurant_name.split()
    if len(words) > 1:
        # Prendre les mots significatifs
        significant_words = [w for w in words if w.lower() not in ['le', 'la', 'les', 'du', 'de', 'des', 'et', '&']]
        if significant_words:
            significant_name = ' '.join(significant_words)
            variants.append(significant_name)
            variants.append(normalize_query(significant_name))
    
    # Supprimer les doublons tout en gardant l'ordre
    seen = set()
    unique_variants = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            unique_variants.append(v)
    
    return unique_variants


def search_restaurant(query, api_key, max_results=60, use_type_filter=False, log_file=None):
    """Recherche un restaurant via Google Places API et retourne TOUS les résultats"""
    if not api_key:
        if log_file:
            log(f"❌ Clé API Google manquante", log_file)
        return None
    
    if not GOOGLEMAPS_AVAILABLE:
        if log_file:
            log(f"❌ Module googlemaps non installé. Installez-le avec: pip install googlemaps", log_file)
        return None
    
    gmaps = googlemaps.Client(key=api_key)
    
    try:
        all_results = []
        # Recherche plus large : sans filtre type='restaurant' pour être plus permissif
        if use_type_filter:
            places_result = gmaps.places(query=query, type='restaurant', language='fr')
        else:
            places_result = gmaps.places(query=query, language='fr')
        
        if not places_result.get('results'):
            return None
        
        # Traiter les premiers résultats
        for place in places_result['results']:
            place_id = place.get('place_id')
            if place_id:
                place_details = gmaps.place(place_id=place_id, language='fr')
                place_data = place_details.get('result', place)
            else:
                place_data = place
            
            # Récupérer les horaires
            opening_hours = place_data.get('opening_hours', {})
            horaires = ''
            if opening_hours:
                weekday_text = opening_hours.get('weekday_text', [])
                if weekday_text:
                    horaires = ', '.join(weekday_text)
            
            # Récupérer l'URL du logo depuis les photos Google Places
            logo_url = ''
            photos = place_data.get('photos', [])
            if photos:
                # Prendre la première photo (généralement la meilleure)
                photo_reference = photos[0].get('photo_reference', '')
                if photo_reference:
                    # Construire l'URL de la photo (maxwidth 400 pour le logo)
                    logo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_reference}&key={api_key}"
            
            result_data = {
                'nom': place_data.get('name', ''),
                'adresse_formatee': place_data.get('formatted_address', ''),
                'telephone': place_data.get('formatted_phone_number', ''),
                'site_web': place_data.get('website', ''),
                'url_google_maps': place_data.get('url', ''),
                'note': place_data.get('rating', ''),
                'nombre_avis': place_data.get('user_ratings_total', ''),
                'place_id': place_id or place.get('place_id', ''),
                'latitude': place_data.get('geometry', {}).get('location', {}).get('lat', ''),
                'longitude': place_data.get('geometry', {}).get('location', {}).get('lng', ''),
                'horaires_ouverture': horaires,
                'logo_url': logo_url,
                'lien_menu': '',
                'lien_reservation': '',
                'instagram': '',
                'facebook': '',
            }
            all_results.append(result_data)
        
        # Si on a un token de pagination, continuer à chercher
        next_page_token = places_result.get('next_page_token')
        page_count = 1
        
        while next_page_token and len(all_results) < max_results and page_count < 3:
            time.sleep(2)  # Attendre que le token soit valide
            try:
                places_result = gmaps.places(query=None, page_token=next_page_token, language='fr')
                if places_result.get('results'):
                    for place in places_result['results']:
                        place_id = place.get('place_id')
                        if place_id:
                            place_details = gmaps.place(place_id=place_id, language='fr')
                            place_data = place_details.get('result', place)
                        else:
                            place_data = place
                        
                        # Récupérer les horaires
                        opening_hours = place_data.get('opening_hours', {})
                        horaires = ''
                        if opening_hours:
                            weekday_text = opening_hours.get('weekday_text', [])
                            if weekday_text:
                                horaires = ', '.join(weekday_text)
                        
                        # Récupérer l'URL du logo depuis les photos Google Places
                        logo_url = ''
                        photos = place_data.get('photos', [])
                        if photos:
                            photo_reference = photos[0].get('photo_reference', '')
                            if photo_reference:
                                logo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={photo_reference}&key={api_key}"
                        
                        result_data = {
                            'nom': place_data.get('name', ''),
                            'adresse_formatee': place_data.get('formatted_address', ''),
                            'telephone': place_data.get('formatted_phone_number', ''),
                            'site_web': place_data.get('website', ''),
                            'url_google_maps': place_data.get('url', ''),
                            'note': place_data.get('rating', ''),
                            'nombre_avis': place_data.get('user_ratings_total', ''),
                            'place_id': place_id or place.get('place_id', ''),
                            'latitude': place_data.get('geometry', {}).get('location', {}).get('lat', ''),
                            'longitude': place_data.get('geometry', {}).get('location', {}).get('lng', ''),
                            'horaires_ouverture': horaires,
                            'logo_url': logo_url,
                            'lien_menu': '',
                            'lien_reservation': '',
                            'instagram': '',
                            'facebook': '',
                        }
                        all_results.append(result_data)
                
                next_page_token = places_result.get('next_page_token')
                page_count += 1
            except Exception as e:
                if log_file:
                    log(f"      ⚠️  Erreur lors de la pagination: {str(e)[:50]}", log_file)
                break
        
        return all_results if all_results else None
    except Exception as e:
        if log_file:
            log(f"❌ Erreur lors de la recherche: {str(e)}", log_file)
        return None


def scrape_website_links(website_url, log_file=None):
    """
    Scrape un site web pour extraire les liens menu, réservation, Instagram, Facebook
    
    Args:
        website_url: URL du site web à scraper
        log_file: Chemin du fichier de log (optionnel)
    
    Returns:
        dict: Dictionnaire avec les liens trouvés
    """
    # Toujours essayer d'importer les modules localement (même si l'import global a échoué)
    # Cela permet de fonctionner même si les modules sont dans un environnement virtuel différent
    try:
        import requests
        from bs4 import BeautifulSoup
        scraping_ok = True
    except ImportError as e:
        scraping_ok = False
        if log_file:
            log(f"  ⚠️  Modules requests/beautifulsoup4 non disponibles: {str(e)}", log_file)
            log(f"  💡 Installez-les avec: pip install requests beautifulsoup4", log_file)
        # Retourner immédiatement si les modules ne sont pas disponibles
        return {
            'lien_menu': '',
            'lien_reservation': '',
            'instagram': '',
            'facebook': ''
        }
    
    if not website_url or not website_url.startswith('http'):
        return {
            'lien_menu': '',
            'lien_reservation': '',
            'instagram': '',
            'facebook': ''
        }
    
    result = {
        'lien_menu': '',
        'lien_reservation': '',
        'instagram': '',
        'facebook': ''
    }
    
    try:
        # Headers pour éviter d'être bloqué
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Timeout de 5 secondes pour éviter les attentes trop longues
        response = requests.get(website_url, headers=headers, timeout=5, allow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        base_url = response.url
        
        # Chercher tous les liens
        all_links = soup.find_all('a', href=True)
        
        # Mots-clés pour identifier les liens
        menu_keywords = ['menu', 'carte', 'card', 'menus', 'la-carte']
        reservation_keywords = ['reservation', 'reserver', 'book', 'booking', 'table', 'reserve', 'réserver']
        instagram_keywords = ['instagram.com', 'instagr.am']
        facebook_keywords = ['facebook.com', 'fb.com']
        
        for link in all_links:
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            
            # Menu
            if not result['lien_menu']:
                if any(keyword in href for keyword in menu_keywords) or any(keyword in text for keyword in menu_keywords):
                    full_url = urljoin(base_url, link['href'])
                    if full_url.startswith('http'):
                        result['lien_menu'] = full_url
                        if log_file:
                            log(f"     📋 Menu trouvé: {full_url[:80]}...", log_file)
            
            # Réservation
            if not result['lien_reservation']:
                if any(keyword in href for keyword in reservation_keywords) or any(keyword in text for keyword in reservation_keywords):
                    full_url = urljoin(base_url, link['href'])
                    if full_url.startswith('http'):
                        result['lien_reservation'] = full_url
                        if log_file:
                            log(f"     📅 Réservation trouvée: {full_url[:80]}...", log_file)
            
            # Instagram
            if not result['instagram']:
                if any(keyword in href for keyword in instagram_keywords):
                    full_url = urljoin(base_url, link['href'])
                    if full_url.startswith('http'):
                        result['instagram'] = full_url
                        if log_file:
                            log(f"     📸 Instagram trouvé: {full_url[:80]}...", log_file)
            
            # Facebook
            if not result['facebook']:
                if any(keyword in href for keyword in facebook_keywords):
                    full_url = urljoin(base_url, link['href'])
                    if full_url.startswith('http'):
                        result['facebook'] = full_url
                        if log_file:
                            log(f"     👥 Facebook trouvé: {full_url[:80]}...", log_file)
        
        # Chercher aussi dans les meta tags (pour les réseaux sociaux)
        meta_tags = soup.find_all('meta', property=True)
        for meta in meta_tags:
            property_attr = meta.get('property', '').lower()
            content = meta.get('content', '')
            
            if 'og:image' in property_attr and not result.get('logo_url'):
                # Image Open Graph (peut être un logo)
                pass
            
            if 'instagram' in property_attr or 'instagram' in content.lower():
                if content.startswith('http') and not result['instagram']:
                    result['instagram'] = content
                    if log_file:
                        log(f"     📸 Instagram trouvé (meta): {content[:80]}...", log_file)
            
            if 'facebook' in property_attr or 'facebook' in content.lower():
                if content.startswith('http') and not result['facebook']:
                    result['facebook'] = content
                    if log_file:
                        log(f"     👥 Facebook trouvé (meta): {content[:80]}...", log_file)
        
    except requests.exceptions.Timeout:
        if log_file:
            log(f"  ⚠️  Timeout lors du scraping de {website_url[:50]}...", log_file)
    except requests.exceptions.RequestException as e:
        if log_file:
            log(f"  ⚠️  Erreur lors du scraping de {website_url[:50]}: {str(e)[:100]}", log_file)
    except Exception as e:
        if log_file:
            log(f"  ⚠️  Erreur inattendue lors du scraping: {str(e)[:100]}", log_file)
    
    return result


def extract_arrondissement(address):
    """Extrait le code postal (arrondissement) depuis une adresse Parisienne"""
    if not address:
        return ''
    
    # Chercher le format "75001", "75002", etc. dans l'adresse
    arrondissement_pattern = r'\b(75\d{3})\b'
    match = re.search(arrondissement_pattern, address)
    if match:
        arr_code = match.group(1)
        return arr_code
    
    return ''


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcule la distance en mètres entre deux points GPS (formule de Haversine)"""
    if not all([lat1, lon1, lat2, lon2]):
        return float('inf')
    
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return float('inf')
    
    # Rayon de la Terre en mètres
    R = 6371000
    
    # Conversion en radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    # Formule de Haversine
    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    distance = R * c
    return distance


def load_metro_data():
    """
    Charge les données des lignes de métro depuis le fichier JSON
    Retourne un dictionnaire: nom_station -> [liste des numéros de lignes]
    """
    try:
        # Chemin vers le fichier JSON
        script_dir = Path(__file__).parent
        metro_json_path = script_dir / 'data' / 'metro_lines.json'
        
        if not metro_json_path.exists():
            # Essayer un autre chemin
            metro_json_path = script_dir.parent / 'data' / 'metro_lines.json'
            if not metro_json_path.exists():
                return {}
        
        with open(metro_json_path, 'r', encoding='utf-8') as f:
            metro_data = json.load(f)
        
        # Construire un dictionnaire: nom_station -> [lignes]
        station_to_lines = {}
        
        for ligne in metro_data.get('lignes', []):
            ligne_num = ligne.get('numero', '')
            for station in ligne.get('stations_detaillees', []):
                station_nom = station.get('nom', '').strip()
                if station_nom:
                    # Normaliser le nom de la station
                    station_normalized = normalize_station_name(station_nom)
                    if station_normalized not in station_to_lines:
                        station_to_lines[station_normalized] = []
                    if ligne_num not in station_to_lines[station_normalized]:
                        station_to_lines[station_normalized].append(ligne_num)
        
        return station_to_lines
    except Exception as e:
        print(f"⚠️  Erreur lors du chargement des données métro: {e}")
        return {}


def normalize_station_name(station_name):
    """
    Normalise le nom d'une station pour la comparaison
    Enlève les accents, met en minuscule, supprime les caractères spéciaux
    """
    if not station_name:
        return ''
    
    # Enlever les accents
    normalized = unicodedata.normalize('NFD', station_name.lower())
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    
    # Supprimer les caractères spéciaux et normaliser les espaces
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    normalized = ' '.join(normalized.split())
    
    return normalized


def get_metro_lines_from_station_name(station_name, metro_data_cache=None):
    """
    Retourne toutes les lignes de métro pour une station parisienne
    Utilise le fichier JSON des lignes de métro
    
    Args:
        station_name: Nom de la station à rechercher
        metro_data_cache: Cache des données métro (optionnel, pour éviter de recharger)
    
    Returns:
        list: Liste des numéros de lignes (ex: ['1', '11'])
    """
    # Charger les données si pas en cache
    if metro_data_cache is None:
        metro_data_cache = load_metro_data()
    
    if not metro_data_cache:
        return []
    
    if not station_name or not station_name.strip():
        return []
    
    # Normaliser le nom de la station recherchée
    station_normalized = normalize_station_name(station_name)
    
    if not station_normalized:
        return []
    
    # Chercher une correspondance exacte
    if station_normalized in metro_data_cache:
        return sorted(metro_data_cache[station_normalized], key=lambda x: (len(x), x))
    
    # Chercher une correspondance partielle (le nom recherché contient le nom de la station ou vice versa)
    for db_station, lines in metro_data_cache.items():
        if station_normalized in db_station or db_station in station_normalized:
            return sorted(lines, key=lambda x: (len(x), x))
    
    # Si pas de correspondance, essayer de chercher des mots-clés communs
    station_words = set(station_normalized.split())
    if len(station_words) >= 2:
        # Si au moins 2 mots en commun, considérer comme correspondance
        for db_station, lines in metro_data_cache.items():
            db_words = set(db_station.split())
            common_words = station_words & db_words
            if len(common_words) >= 2:
                return sorted(lines, key=lambda x: (len(x), x))
    
    # Dernière tentative : chercher avec le premier mot significatif (si > 3 caractères)
    # et au moins un autre mot
    significant_words = [w for w in station_words if len(w) > 3]
    if len(significant_words) >= 1:
        for db_station, lines in metro_data_cache.items():
            db_words = set(db_station.split())
            # Si le premier mot significatif est présent et qu'il y a au moins un autre mot en commun
            if significant_words[0] in db_words:
                common = station_words & db_words
                if len(common) >= 1:
                    return sorted(lines, key=lambda x: (len(x), x))
    
    # Dernière tentative : recherche par similarité (distance de Levenshtein simplifiée)
    # Si le nom recherché est très similaire à un nom de la base (au moins 70% de caractères communs)
    best_match = None
    best_score = 0
    for db_station, lines in metro_data_cache.items():
        # Calculer un score de similarité simple
        common_chars = set(station_normalized) & set(db_station)
        total_chars = len(set(station_normalized) | set(db_station))
        if total_chars > 0:
            score = len(common_chars) / total_chars
            if score > best_score and score >= 0.7:
                best_score = score
                best_match = lines
    
    if best_match:
        return sorted(best_match, key=lambda x: (len(x), x))
    
    return []


# Cache global pour les données métro (chargé une seule fois)
_METRO_DATA_CACHE = None

def get_metro_data_cache():
    """Retourne le cache des données métro, le charge si nécessaire"""
    global _METRO_DATA_CACHE
    if _METRO_DATA_CACHE is None:
        _METRO_DATA_CACHE = load_metro_data()
    return _METRO_DATA_CACHE


def extract_arrondissement(address):
    """Extrait le code postal (arrondissement) depuis une adresse Parisienne"""
    if not address:
        return ''
    
    # Chercher le format "75001", "75002", etc. dans l'adresse
    arrondissement_pattern = r'\b(75\d{3})\b'
    match = re.search(arrondissement_pattern, address)
    if match:
        arr_code = match.group(1)
        return arr_code
    
    return ''


def find_nearest_metro_stations(restaurant_lat, restaurant_lng, gmaps_client, limit=2, log_file=None):
    """Trouve les stations de métro les plus proches d'un restaurant avec toutes leurs lignes"""
    if not restaurant_lat or not restaurant_lng:
        if log_file:
            log(f"  ⚠️  Coordonnées GPS manquantes pour le restaurant", log_file)
        return []
    
    if log_file:
        log(f"  🚇 Recherche des stations de métro les plus proches...", log_file)
        log(f"     Restaurant: ({restaurant_lat}, {restaurant_lng})", log_file)
    
    # Utiliser l'API Google Places pour trouver les stations proches directement
    try:
        # Rechercher les stations de métro proches avec l'API
        location_str = f"{restaurant_lat},{restaurant_lng}"
        places_result = gmaps_client.places_nearby(
            location=location_str,
            radius=2000,  # 2km de rayon
            type='subway_station',
            language='fr'
        )
        
        if not places_result.get('results'):
            if log_file:
                log(f"  ⚠️  Aucune station trouvée via l'API Google Places", log_file)
            return []
        
        # Extraire les stations et calculer les distances
        distances = []
        for place in places_result['results']:
            place_name = place.get('name', '')
            place_id = place.get('place_id', '')
            location = place.get('geometry', {}).get('location', {})
            lat = location.get('lat')
            lng = location.get('lng')
            
            if lat and lng:
                distance = haversine_distance(restaurant_lat, restaurant_lng, lat, lng)
                
                # Récupérer toutes les lignes de la station
                lignes = []
                
                # Méthode 1: Utiliser les détails complets de la station
                if place_id:
                    try:
                        place_details = gmaps_client.place(place_id=place_id, language='fr')
                        detail_result = place_details.get('result', {})
                        
                        # Chercher dans les types et autres champs
                        types = detail_result.get('types', [])
                        for t in types:
                            # Certains types peuvent contenir des infos sur les lignes
                            if 'line' in t.lower() or 'ligne' in t.lower():
                                # Essayer d'extraire un numéro
                                num_match = re.search(r'(\d+)', t)
                                if num_match:
                                    lignes.append(num_match.group(1))
                        
                        # Chercher dans l'adresse ou le nom formaté
                        formatted_name = detail_result.get('name', '')
                        address = detail_result.get('formatted_address', '')
                        full_text = f"{formatted_name} {address}".lower()
                        
                        # Extraire les numéros de lignes mentionnés
                        for i in range(1, 15):
                            if f'ligne {i}' in full_text or f' m{i} ' in full_text or f' m{i}' in full_text:
                                if str(i) not in lignes:
                                    lignes.append(str(i))
                    except Exception as e:
                        if log_file:
                            log(f"     ⚠️  Erreur détails station {place_name}: {str(e)[:50]}", log_file)
                
                # Méthode 2: Utiliser le fichier JSON des lignes de métro
                if not lignes:
                    metro_cache = get_metro_data_cache()
                    lignes = get_metro_lines_from_station_name(place_name, metro_cache)
                    if lignes and log_file:
                        log(f"     📍 Lignes trouvées via JSON: {', '.join(lignes)}", log_file)
                
                # Si toujours aucune ligne trouvée, essayer d'extraire depuis le nom directement
                if not lignes:
                    for i in range(1, 15):
                        if f'ligne {i}' in place_name.lower() or f' m{i} ' in place_name.lower():
                            lignes.append(str(i))
                
                # Trier les lignes numériquement
                lignes = sorted(set(lignes), key=lambda x: int(x) if x.isdigit() else 999)
                
                distances.append({
                    'nom': place_name,
                    'lignes': lignes,  # Liste de toutes les lignes
                    'lignes_str': ', '.join(lignes) if lignes else '?',  # Pour l'affichage
                    'distance_metres': round(distance, 0),
                    'latitude': lat,
                    'longitude': lng
                })
        
        # Trier par distance et prendre les N plus proches
        distances.sort(key=lambda x: x['distance_metres'])
        nearest = distances[:limit]
        
        if nearest and log_file:
            log(f"  ✅ {len(nearest)} station(s) trouvée(s):", log_file)
            for st in nearest:
                lignes_display = st['lignes_str'] if st['lignes'] else '?'
                log(f"     - {st['nom']} (Lignes: {lignes_display}) - {st['distance_metres']:.0f}m", log_file)
        elif log_file:
            log(f"  ⚠️  Aucune station trouvée", log_file)
        
        return nearest
        
    except Exception as e:
        if log_file:
            log(f"  ❌ Erreur lors de la recherche des stations: {str(e)[:100]}", log_file)
        return []


def aggregate_results_by_restaurant(results):
    """Agrège toutes les occurrences d'un même restaurant sur une seule ligne"""
    # Grouper par nom_source
    grouped = defaultdict(list)
    for result in results:
        nom_source = result.get('nom_source', '')
        if nom_source:
            grouped[nom_source].append(result)
    
    aggregated_results = []
    
    for nom_source, occurrences in grouped.items():
        if not occurrences:
            continue
        
        # Créer une ligne agrégée
        aggregated = {
            'nom_source': nom_source,
            'nombre_occurrences': len(occurrences),
        }
        
        # Colonnes à agréger avec des pipes
        columns_to_aggregate = [
            'nom', 'adresse_formatee', 'arrondissement', 'telephone', 'site_web',
            'url_google_maps', 'note', 'nombre_avis', 'place_id',
            'station_metro_1', 
            'distance_station_1_metres', 'station_metro_2',
            'distance_station_2_metres', 'statut', 'logo_url',
            'lien_menu', 'lien_reservation', 'instagram', 'facebook'
        ]
        
        # Colonnes de lignes de métro : garder les lignes groupées par station
        lignes_columns = ['lignes_metro_1', 'lignes_metro_2']
        station_columns = ['station_metro_1', 'station_metro_2']
        
        for col in columns_to_aggregate:
            values = []
            for occ in occurrences:
                val = occ.get(col, '')
                if val and str(val).strip() and str(val).lower() != 'nan':
                    values.append(str(val).strip())
            
            if values:
                # Supprimer les doublons tout en gardant l'ordre
                unique_values = []
                seen = set()
                for v in values:
                    if v not in seen:
                        unique_values.append(v)
                        seen.add(v)
                aggregated[col] = ' | '.join(unique_values)
            else:
                aggregated[col] = ''
        
        # Traitement spécial pour les lignes de métro : garder les lignes groupées par station
        # Chaque station garde ses propres lignes, séparées par | entre les stations
        for idx, lignes_col in enumerate(lignes_columns):
            station_col = station_columns[idx]
            lignes_by_station = []
            
            # Créer un mapping station -> lignes pour éviter les doublons de stations
            station_lignes_map = {}
            for occ in occurrences:
                station = occ.get(station_col, '').strip()
                lignes_str = occ.get(lignes_col, '').strip()
                
                if station and lignes_str and str(lignes_str).lower() != 'nan':
                    # Si cette station n'a pas encore été vue, ou si les lignes sont différentes
                    if station not in station_lignes_map:
                        station_lignes_map[station] = lignes_str
                    else:
                        # Si la station existe déjà, fusionner les lignes (dédupliquer)
                        existing_lignes = station_lignes_map[station]
                        # Parser et fusionner
                        all_lignes = []
                        for ls in [existing_lignes, lignes_str]:
                            if ls:
                                lignes_list = re.split(r'[,|]', ls)
                                for ligne in lignes_list:
                                    ligne = ligne.strip()
                                    if ligne and ligne != '?' and ligne.isdigit():
                                        if ligne not in all_lignes:
                                            all_lignes.append(ligne)
                        if all_lignes:
                            all_lignes = sorted(all_lignes, key=lambda x: int(x) if x.isdigit() else 999)
                            station_lignes_map[station] = ', '.join(all_lignes)
            
            # Construire la liste des lignes dans l'ordre des stations trouvées
            # (pour correspondre à l'ordre des stations dans station_metro_X)
            stations_order = []
            for occ in occurrences:
                station = occ.get(station_col, '').strip()
                if station and station not in stations_order:
                    stations_order.append(station)
            
            # Construire la chaîne finale avec les lignes dans l'ordre des stations
            lignes_list = []
            for station in stations_order:
                if station in station_lignes_map:
                    lignes_list.append(station_lignes_map[station])
            
            if lignes_list:
                aggregated[lignes_col] = ' | '.join(lignes_list)
            else:
                aggregated[lignes_col] = ''
        
        # Pour les horaires : prendre seulement les premiers
        horaires_values = []
        for occ in occurrences:
            horaires = occ.get('horaires_ouverture', '')
            if horaires and str(horaires).strip() and str(horaires).lower() != 'nan':
                horaires_values.append(str(horaires).strip())
                break  # Prendre seulement les premiers
        
        aggregated['horaires_ouverture'] = horaires_values[0] if horaires_values else ''
        
        # Coordonnées GPS : prendre les premières
        lat_values = [occ.get('latitude', '') for occ in occurrences if occ.get('latitude')]
        lng_values = [occ.get('longitude', '') for occ in occurrences if occ.get('longitude')]
        aggregated['latitude'] = lat_values[0] if lat_values else ''
        aggregated['longitude'] = lng_values[0] if lng_values else ''
        
        aggregated_results.append(aggregated)
    
    return aggregated_results


def search_restaurants_from_excel(excel_path: str, name_column: str, request=None, log_file_path: str = None, output_dir: str = None):
    """
    Recherche des restaurants depuis un fichier Excel
    
    Args:
        excel_path: Chemin vers le fichier Excel
        name_column: Nom de la colonne contenant les noms de restaurants
        request: Objet request Django (optionnel) pour déterminer l'environnement Firebase
        log_file_path: Chemin du fichier de log
        output_dir: Répertoire de sortie pour le fichier Excel
    """
    if not log_file_path:
        from config import BACKUP_DIR
        # Path et datetime sont déjà importés en haut du fichier, pas besoin de les réimporter
        BASE_DIR = Path(__file__).resolve().parent.parent
        ts_dir = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_base = Path(BACKUP_DIR) if isinstance(BACKUP_DIR, str) else BACKUP_DIR
        search_dir = backup_base / f"search_{ts_dir}"
        search_dir.mkdir(parents=True, exist_ok=True)
        log_file_path = str(search_dir / "search_run.log")
    
    if not output_dir:
        output_dir = os.path.dirname(log_file_path)
    
    log_file = log_file_path
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    log("=" * 60, log_file)
    log("🔍 RECHERCHE DE RESTAURANTS VIA GOOGLE PLACES API", log_file)
    log("=" * 60, log_file)
    log(f"📁 Fichier Excel: {excel_path}", log_file)
    log(f"📋 Colonne des noms: {name_column}", log_file)
    log("", log_file)
    
    # Récupérer la clé API Google depuis les variables d'environnement Django
    # Essayer plusieurs noms de variables d'environnement
    API_KEY = (
        os.getenv('GOOGLE_PLACES_API_KEY') or 
        os.getenv('GOOGLE_MAPS_API_KEY') or 
        os.getenv('GOOGLE_PLACE_ID') or
        os.getenv('GOOGLE_API_KEY')
    )
    
    log(f"🔑 Recherche de la clé API Google...", log_file)
    if not API_KEY:
        error_msg = "❌ Clé API Google non trouvée. Définissez GOOGLE_PLACES_API_KEY, GOOGLE_MAPS_API_KEY, GOOGLE_PLACE_ID ou GOOGLE_API_KEY dans votre fichier .env"
        log(error_msg, log_file)
        log("💡 Ajoutez la ligne suivante dans votre fichier .env:", log_file)
        log("   GOOGLE_PLACES_API_KEY=votre_cle_api_ici", log_file)
        raise ValueError(error_msg)
    
    log(f"✅ Clé API Google trouvée (longueur: {len(API_KEY)} caractères)", log_file)
    
    if not GOOGLEMAPS_AVAILABLE:
        error_msg = "❌ Module googlemaps non installé. Installez-le avec: pip install googlemaps"
        log(error_msg, log_file)
        raise ImportError(error_msg)
    
    log(f"✅ Module googlemaps disponible", log_file)
    
    # Initialiser le client Google Maps
    try:
        gmaps = googlemaps.Client(key=API_KEY)
        log(f"✅ Client Google Maps initialisé", log_file)
        log("", log_file)
    except Exception as e:
        error_msg = f"❌ Erreur lors de l'initialisation du client Google Maps: {str(e)}"
        log(error_msg, log_file)
        raise
    
    # Lire le fichier Excel
    log(f"📖 Lecture du fichier Excel: {excel_path}", log_file)
    try:
        df = pd.read_excel(excel_path, engine='openpyxl')
        log(f"✅ Fichier Excel lu: {len(df)} lignes, {len(df.columns)} colonnes", log_file)
        log(f"📋 Colonnes disponibles: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}", log_file)
        
        if name_column not in df.columns:
            error_msg = f"❌ Colonne '{name_column}' non trouvée dans le fichier Excel"
            log(error_msg, log_file)
            log(f"📋 Colonnes disponibles: {', '.join(df.columns.tolist())}", log_file)
            raise ValueError(error_msg)
        
        # Extraire les noms de restaurants
        restaurants_data = []
        for idx, row in df.iterrows():
            name = str(row[name_column]).strip() if pd.notna(row[name_column]) else ''
            if name and name.lower() not in ['nan', '']:
                restaurants_data.append({
                    'name': name,
                    'reference_urls': []  # Pour l'instant, pas de URLs de référence
                })
        
        log(f"🍽️  {len(restaurants_data)} restaurants à rechercher", log_file)
        log("", log_file)
        
    except Exception as e:
        error_msg = f"❌ Erreur lors de la lecture du fichier Excel: {str(e)}"
        log(error_msg, log_file)
        raise
    
    # Rechercher chaque restaurant
    all_results = []
    restaurants_trouves = 0
    
    log(f"🚀 Démarrage de la recherche pour {len(restaurants_data)} restaurants", log_file)
    log("", log_file)
    
    for idx, restaurant_info in enumerate(restaurants_data, 1):
        restaurant_name = restaurant_info['name']
        
        log(f"\n{'='*60}", log_file)
        log(f"Restaurant {idx}/{len(restaurants_data)}: {restaurant_name}", log_file)
        log(f"{'='*60}", log_file)
        
        # Générer plusieurs variantes de recherche
        search_variants = generate_search_variants(restaurant_name)
        log(f"  🔍 Recherche avec {len(search_variants)} variantes...", log_file)
        
        results = []
        seen_place_ids = set()
        
        # Essayer chaque variante (limiter à 3 premières variantes pour être plus rapide)
        max_variants = min(3, len(search_variants))
        for variant_idx, variant in enumerate(search_variants[:max_variants], 1):
            log(f"     Variante {variant_idx}/{max_variants}: '{variant}'...", log_file)
            try:
                variant_results = search_restaurant(variant, API_KEY, max_results=20, use_type_filter=False, log_file=log_file)
                
                if variant_results:
                    # Ajouter seulement les nouveaux résultats (éviter les doublons par place_id)
                    new_results_count = 0
                    for result in variant_results:
                        place_id = result.get('place_id', '')
                        if place_id and place_id not in seen_place_ids:
                            seen_place_ids.add(place_id)
                            results.append(result)
                            new_results_count += 1
                    
                    log(f"       ✅ {new_results_count} nouveau(x) résultat(s) trouvé(s) ({len(variant_results)} total avec cette variante)", log_file)
                    
                    # Si on a déjà assez de résultats, on peut s'arrêter
                    if len(results) >= 10:
                        log(f"       ⚠️  Suffisamment de résultats trouvés ({len(results)}), arrêt de la recherche pour ce restaurant", log_file)
                        break
                else:
                    log(f"       ❌ Aucun résultat avec cette variante", log_file)
            except Exception as e:
                log(f"       ⚠️  Erreur lors de la recherche avec cette variante: {str(e)[:100]}", log_file)
                continue
            
            # Petite pause entre les variantes pour éviter de surcharger l'API
            if variant_idx < max_variants:
                time.sleep(0.3)
        
        if results:
            log(f"  ✅ Total: {len(results)} résultat(s) unique(s) trouvé(s)", log_file)
            
            # Limiter à 3 meilleurs résultats par restaurant pour éviter trop de données
            results_to_process = results[:3]
            if len(results) > 3:
                log(f"  📊 Limitation à 3 meilleurs résultats sur {len(results)} trouvés", log_file)
            
            # Pour chaque résultat, trouver les stations de métro, extraire l'arrondissement et scraper le site web
            for result_idx, result in enumerate(results_to_process, 1):
                result['nom_source'] = restaurant_name
                result['statut'] = 'Trouvé'
                
                log(f"  📍 Traitement du résultat {result_idx}/{len(results_to_process)}: {result.get('nom', 'N/A')}", log_file)
                
                # Extraire l'arrondissement
                address = result.get('adresse_formatee', '')
                arrondissement = extract_arrondissement(address)
                result['arrondissement'] = arrondissement
                if arrondissement:
                    log(f"     📍 Arrondissement: {arrondissement}", log_file)
                
                # Trouver les stations de métro les plus proches
                restaurant_lat = result.get('latitude')
                restaurant_lng = result.get('longitude')
                if restaurant_lat and restaurant_lng:
                    try:
                        nearest_stations = find_nearest_metro_stations(
                            restaurant_lat, restaurant_lng, gmaps, limit=2, log_file=log_file
                        )
                    except Exception as e:
                        log(f"     ⚠️  Erreur lors de la recherche des stations: {str(e)[:100]}", log_file)
                        nearest_stations = []
                else:
                    log(f"     ⚠️  Coordonnées GPS manquantes", log_file)
                    nearest_stations = []
                
                # Ajouter les stations au résultat (avec toutes les lignes)
                if len(nearest_stations) >= 1:
                    st1 = nearest_stations[0]
                    result['station_metro_1'] = st1['nom']
                    result['lignes_metro_1'] = ', '.join(st1.get('lignes', [])) if st1.get('lignes') else '?'
                    result['distance_station_1_metres'] = int(st1['distance_metres'])
                else:
                    result['station_metro_1'] = ''
                    result['lignes_metro_1'] = ''
                    result['distance_station_1_metres'] = ''
                
                if len(nearest_stations) >= 2:
                    st2 = nearest_stations[1]
                    result['station_metro_2'] = st2['nom']
                    result['lignes_metro_2'] = ', '.join(st2.get('lignes', [])) if st2.get('lignes') else '?'
                    result['distance_station_2_metres'] = int(st2['distance_metres'])
                else:
                    result['station_metro_2'] = ''
                    result['lignes_metro_2'] = ''
                    result['distance_station_2_metres'] = ''
                
                # Scraper le site web pour extraire menu, réservation, Instagram, Facebook
                website_url = result.get('site_web', '')
                if website_url:
                    log(f"     🌐 Scraping du site web: {website_url[:60]}...", log_file)
                    scraped_links = scrape_website_links(website_url, log_file=log_file)
                    result['lien_menu'] = scraped_links.get('lien_menu', '')
                    result['lien_reservation'] = scraped_links.get('lien_reservation', '')
                    result['instagram'] = scraped_links.get('instagram', '')
                    result['facebook'] = scraped_links.get('facebook', '')
                else:
                    log(f"     ⚠️  Pas de site web disponible pour le scraping", log_file)
            
            all_results.extend(results_to_process)
            restaurants_trouves += 1
            log(f"  ✅ {len(results_to_process)} résultat(s) ajouté(s) pour '{restaurant_name}'", log_file)
        else:
            log(f"  ❌ Aucun résultat trouvé pour '{restaurant_name}'", log_file)
        
        # Délai entre les recherches pour éviter de surcharger l'API
        if idx < len(restaurants_data):
            log(f"  ⏳ Pause de 1 seconde avant le prochain restaurant...", log_file)
            time.sleep(1)
    
    # Sauvegarder les résultats
    if all_results:
        log("", log_file)
        log("📊 Agrégation des résultats par restaurant...", log_file)
        aggregated_results = aggregate_results_by_restaurant(all_results)
        log(f"✅ {len(aggregated_results)} restaurant(s) agrégé(s) à partir de {len(all_results)} occurrence(s)", log_file)
        
        # Créer le DataFrame
        df_results = pd.DataFrame(aggregated_results)
        
        # Réorganiser les colonnes pour mettre nombre_occurrences et nom_source en premier
        cols = df_results.columns.tolist()
        priority_cols = ['nom_source', 'nombre_occurrences']
        other_cols = [c for c in cols if c not in priority_cols]
        df_results = df_results[priority_cols + other_cols]
        
        # Générer le nom de fichier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"restaurants_recherche_{timestamp}.xlsx"
        output_file = output_path / filename
        
        # Sauvegarder en Excel
        df_results.to_excel(output_file, index=False, engine='openpyxl')
        log(f"✅ Résultats sauvegardés dans : {output_file}", log_file)
        log(f"📊 {len(aggregated_results)} restaurant(s) trouvé(s)", log_file)
        
        log("", log_file)
        log("=" * 60, log_file)
        log("✅ Recherche terminée", log_file)
        log(f"📊 {restaurants_trouves}/{len(restaurants_data)} restaurants trouvés", log_file)
        log(f"📁 Fichier de résultat: {output_file}", log_file)
        log("=" * 60, log_file)
        
        return {
            'success': True,
            'found': restaurants_trouves,
            'total': len(restaurants_data),
            'results_count': len(aggregated_results),
            'output_file': str(output_file)
        }
    else:
        log("", log_file)
        log("❌ Aucun résultat trouvé", log_file)
        return {
            'success': False,
            'found': 0,
            'total': len(restaurants_data),
            'results_count': 0,
            'output_file': None
        }

