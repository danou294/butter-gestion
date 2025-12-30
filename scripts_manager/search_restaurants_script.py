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

try:
    import googlemaps
    GOOGLEMAPS_AVAILABLE = True
except ImportError:
    GOOGLEMAPS_AVAILABLE = False

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


def find_nearest_metro_stations(restaurant_lat, restaurant_lng, gmaps_client, limit=2, log_file=None):
    """Trouve les stations de métro les plus proches d'un restaurant"""
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
            location = place.get('geometry', {}).get('location', {})
            lat = location.get('lat')
            lng = location.get('lng')
            
            if lat and lng:
                distance = haversine_distance(restaurant_lat, restaurant_lng, lat, lng)
                
                # Essayer d'extraire la ligne depuis le nom
                ligne = '?'
                nom_ligne = 'Inconnue'
                # Chercher des patterns comme "Ligne 1", "Métro 1", etc.
                ligne_match = re.search(r'(?:ligne|métro|metro)\s*(\d+)', place_name.lower())
                if ligne_match:
                    ligne = ligne_match.group(1)
                    nom_ligne = f"Ligne {ligne}"
                
                distances.append({
                    'nom': place_name,
                    'ligne': ligne,
                    'nom_ligne': nom_ligne,
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
                log(f"     - {st['nom']} (Ligne {st['ligne']}) - {st['distance_metres']:.0f}m", log_file)
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
            'station_metro_1', 'ligne_metro_1', 
            'distance_station_1_metres', 'station_metro_2', 'ligne_metro_2',
            'distance_station_2_metres', 'statut'
        ]
        
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
        from datetime import datetime
        from config import BACKUP_DIR
        # Path est déjà importé en haut du fichier, pas besoin de le réimporter
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
        
        # Essayer chaque variante
        for variant_idx, variant in enumerate(search_variants, 1):
            log(f"     Variante {variant_idx}/{len(search_variants)}: '{variant}'...", log_file)
            variant_results = search_restaurant(variant, API_KEY, max_results=60, use_type_filter=False, log_file=log_file)
            
            if variant_results:
                # Ajouter seulement les nouveaux résultats (éviter les doublons par place_id)
                for result in variant_results:
                    place_id = result.get('place_id', '')
                    if place_id and place_id not in seen_place_ids:
                        seen_place_ids.add(place_id)
                        results.append(result)
                
                log(f"       ✅ {len(variant_results)} résultat(s) trouvé(s) avec cette variante", log_file)
                
                # Si on a déjà beaucoup de résultats, on peut s'arrêter
                if len(results) >= 50:
                    log(f"       ⚠️  Limite de résultats atteinte, arrêt de la recherche", log_file)
                    break
            else:
                log(f"       ❌ Aucun résultat avec cette variante", log_file)
            
            # Petite pause entre les variantes
            if variant_idx < len(search_variants):
                time.sleep(0.5)
        
        if results:
            log(f"  ✅ Total: {len(results)} résultat(s) unique(s) trouvé(s)", log_file)
            
            # Pour chaque résultat, trouver les stations de métro et extraire l'arrondissement
            for result in results:
                result['nom_source'] = restaurant_name
                result['statut'] = 'Trouvé'
                
                # Extraire l'arrondissement
                address = result.get('adresse_formatee', '')
                arrondissement = extract_arrondissement(address)
                result['arrondissement'] = arrondissement
                
                # Trouver les stations de métro les plus proches
                restaurant_lat = result.get('latitude')
                restaurant_lng = result.get('longitude')
                if restaurant_lat and restaurant_lng:
                    nearest_stations = find_nearest_metro_stations(
                        restaurant_lat, restaurant_lng, gmaps, limit=2, log_file=log_file
                    )
                else:
                    nearest_stations = []
                
                # Ajouter les stations au résultat
                if len(nearest_stations) >= 1:
                    result['station_metro_1'] = nearest_stations[0]['nom']
                    result['ligne_metro_1'] = nearest_stations[0]['ligne']
                    result['distance_station_1_metres'] = int(nearest_stations[0]['distance_metres'])
                else:
                    result['station_metro_1'] = ''
                    result['ligne_metro_1'] = ''
                    result['distance_station_1_metres'] = ''
                
                if len(nearest_stations) >= 2:
                    result['station_metro_2'] = nearest_stations[1]['nom']
                    result['ligne_metro_2'] = nearest_stations[1]['ligne']
                    result['distance_station_2_metres'] = int(nearest_stations[1]['distance_metres'])
                else:
                    result['station_metro_2'] = ''
                    result['ligne_metro_2'] = ''
                    result['distance_station_2_metres'] = ''
            
            all_results.extend(results)
            restaurants_trouves += 1
        else:
            log(f"  ❌ Aucun résultat trouvé pour '{restaurant_name}'", log_file)
        
        # Délai entre les recherches
        if idx < len(restaurants_data):
            time.sleep(2)
    
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

