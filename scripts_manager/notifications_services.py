"""
Services pour l'envoi de notifications push via Firebase Cloud Messaging
"""
import logging
from firebase_admin import messaging
from .users_views import get_firebase_app

logger = logging.getLogger(__name__)

DEFAULT_SOUND = "default"
DEFAULT_BADGE = 1


def send_push_notification(token, title, body, data=None):
    """
    Envoie une notification push à un utilisateur
    
    Args:
        token (str): Le token FCM de l'utilisateur
        title (str): Le titre de la notification
        body (str): Le corps de la notification
        data (dict): Données supplémentaires (optionnel)
    
    Returns:
        str: L'ID du message envoyé
    """
    try:
        get_firebase_app()
        
        # Convertir les données en strings (requis par FCM)
        fcm_data = {}
        if data:
            fcm_data = {str(key): str(value) for key, value in data.items()}
        
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=fcm_data,
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound=DEFAULT_SOUND,
                        badge=DEFAULT_BADGE,
                    )
                )
            ),
        )
        
        response = messaging.send(message)
        logger.info(f"✅ Notification envoyée avec succès: {response}")
        return response
    except Exception as error:
        logger.error(f"❌ Erreur lors de l'envoi de la notification: {error}")
        raise


def send_push_notification_to_multiple(tokens, title, body, data=None):
    """
    Envoie une notification à plusieurs utilisateurs
    
    Args:
        tokens (list): Les tokens FCM des utilisateurs
        title (str): Le titre de la notification
        body (str): Le corps de la notification
        data (dict): Données supplémentaires (optionnel)
    
    Returns:
        dict: Résultat avec successCount et failureCount
    """
    try:
        get_firebase_app()
        
        logger.info(f"📤 [MULTIPLE] Préparation de l'envoi à {len(tokens)} tokens")
        logger.info(f"📝 [MULTIPLE] Titre: \"{title}\"")
        logger.info(f"📝 [MULTIPLE] Corps: \"{body}\"")
        
        # Limite FCM pour MulticastMessage (500 tokens maximum)
        # Mais on utilise 100 pour éviter "Too many open files"
        MAX_TOKENS_PER_BATCH = 100
        
        # Convertir les données en strings
        fcm_data = {}
        if data:
            fcm_data = {str(key): str(value) for key, value in data.items()}
        
        # Diviser les tokens en batches de 500 maximum
        total_success = 0
        total_failure = 0
        total_batches = (len(tokens) + MAX_TOKENS_PER_BATCH - 1) // MAX_TOKENS_PER_BATCH
        
        logger.info(f"📦 [MULTIPLE] Division en {total_batches} batch(s) de maximum {MAX_TOKENS_PER_BATCH} tokens")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * MAX_TOKENS_PER_BATCH
            end_idx = min(start_idx + MAX_TOKENS_PER_BATCH, len(tokens))
            batch_tokens = tokens[start_idx:end_idx]
            
            logger.info(f"📤 [MULTIPLE] Envoi du batch {batch_num + 1}/{total_batches} ({len(batch_tokens)} tokens)...")
            
            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=fcm_data,
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound=DEFAULT_SOUND,
                            badge=DEFAULT_BADGE,
                        )
                    )
                ),
                tokens=batch_tokens,
            )
            
            logger.info(f"🚀 [MULTIPLE] Envoi du batch {batch_num + 1} via Firebase Admin SDK...")
            response = messaging.send_each_for_multicast(message)
            
            batch_success = response.success_count
            batch_failure = response.failure_count
            total_success += batch_success
            total_failure += batch_failure
            
            logger.info(f"✅ [MULTIPLE] Batch {batch_num + 1}: {batch_success} succès, {batch_failure} échecs")
            
            if response.failure_count > 0:
                logger.warning(f"⚠️  [MULTIPLE] Batch {batch_num + 1}: {batch_failure} notifications échouées")
                # Afficher les détails des échecs (limité à 5 pour éviter trop de logs)
                error_count = 0
                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        error_count += 1
                        if error_count <= 5:
                            logger.error(f"   ❌ Échec token {idx + 1} du batch {batch_num + 1}: {resp.exception}")
                if error_count > 5:
                    logger.warning(f"   ... et {error_count - 5} autres échecs")
            
            # Ajouter un petit délai entre les batches pour permettre la fermeture des connexions
            if batch_num < total_batches - 1:  # Pas de délai après le dernier batch
                import time
                time.sleep(0.5)  # 500ms de délai entre les batches
        
        logger.info(f"✅ [MULTIPLE] Total: {total_success} notifications envoyées avec succès")
        if total_failure > 0:
            logger.warning(f"❌ [MULTIPLE] Total: {total_failure} notifications échouées")
        
        return {
            'successCount': total_success,
            'failureCount': total_failure,
        }
    except Exception as error:
        logger.error(f"❌ [MULTIPLE] Erreur lors de l'envoi des notifications: {error}")
        raise


def send_push_notification_to_all(title, body, data=None):
    """
    Envoie une notification à tous les utilisateurs (sans personnalisation)
    
    Args:
        title (str): Le titre de la notification
        body (str): Le corps de la notification
        data (dict): Données supplémentaires (optionnel)
    
    Returns:
        dict: Résultat avec successCount et failureCount
    """
    try:
        get_firebase_app()
        from firebase_admin import firestore
        
        logger.info("🚀 [ENVOI À TOUS] Début du processus")
        logger.info(f"📝 [ENVOI À TOUS] Titre: \"{title}\"")
        logger.info(f"📝 [ENVOI À TOUS] Corps: \"{body}\"")
        
        db = firestore.client()
        logger.info("🔗 [ENVOI À TOUS] Connexion à Firestore établie")
        
        # Récupérer tous les tokens depuis la collection 'fcm_tokens'
        logger.info("📂 [ENVOI À TOUS] Récupération des tokens depuis la collection 'fcm_tokens'...")
        tokens_snapshot = db.collection('fcm_tokens').get()
        
        logger.info(f"📊 [ENVOI À TOUS] Nombre de documents trouvés: {len(tokens_snapshot)}")
        
        if not tokens_snapshot:
            logger.warning("⚠️ [ENVOI À TOUS] Aucun token FCM trouvé dans Firestore")
            return {'successCount': 0, 'failureCount': 0, 'totalTokens': 0}
        
        tokens = []
        valid_tokens = 0
        invalid_tokens = 0
        
        logger.info("🔍 [ENVOI À TOUS] Extraction des tokens depuis les documents...")
        for doc in tokens_snapshot:
            token_data = doc.to_dict()
            user_id = doc.id
            
            if token_data.get('token'):
                tokens.append(token_data['token'])
                valid_tokens += 1
                logger.info(f"   ✅ Token valide trouvé pour userId: {user_id}")
            else:
                invalid_tokens += 1
                logger.warning(f"   ⚠️ Document sans token pour userId: {user_id}")
        
        logger.info(f"📱 [ENVOI À TOUS] Résumé de l'extraction:")
        logger.info(f"   - Tokens valides: {valid_tokens}")
        logger.info(f"   - Tokens invalides: {invalid_tokens}")
        logger.info(f"   - Total notifications à envoyer: {len(tokens)}")
        
        if not tokens:
            logger.error("❌ [ENVOI À TOUS] Aucun token valide trouvé, arrêt du processus")
            return {'successCount': 0, 'failureCount': 0, 'totalTokens': 0}
        
        # Envoyer les notifications via multicast
        logger.info("📤 [ENVOI À TOUS] Envoi des notifications via FCM...")
        response = send_push_notification_to_multiple(tokens, title, body, data)
        
        logger.info("📊 [ENVOI À TOUS] Résultats de l'envoi:")
        logger.info(f"   ✅ Notifications envoyées avec succès: {response['successCount']}")
        logger.info(f"   ❌ Notifications échouées: {response['failureCount']}")
        logger.info(f"   📱 Total de notifications traitées: {len(tokens)}")
        
        result = {
            'successCount': response['successCount'],
            'failureCount': response['failureCount'],
            'totalTokens': len(tokens),
        }
        
        logger.info("✅ [ENVOI À TOUS] Processus terminé avec succès")
        return result
    except Exception as error:
        logger.error(f"❌ [ENVOI À TOUS] Erreur lors de l'envoi à tous: {error}")
        raise


def send_push_notification_to_all_with_prenom(title_template, body_template, data=None):
    """
    Envoie une notification personnalisée à tous les utilisateurs avec leurs prénoms
    Chaque notification est personnalisée avec le prénom de l'utilisateur
    
    Args:
        title_template (str): Template du titre (peut contenir {prenom})
        body_template (str): Template du corps (peut contenir {prenom})
        data (dict): Données supplémentaires (optionnel)
    
    Returns:
        dict: Résultat avec successCount et failureCount
    """
    try:
        get_firebase_app()
        from firebase_admin import firestore
        
        logger.info("🚀 [ENVOI À TOUS AVEC PRÉNOM] Début du processus")
        logger.info(f"📝 [ENVOI À TOUS AVEC PRÉNOM] Template titre: \"{title_template}\"")
        logger.info(f"📝 [ENVOI À TOUS AVEC PRÉNOM] Template corps: \"{body_template}\"")
        
        db = firestore.client()
        logger.info("🔗 [ENVOI À TOUS AVEC PRÉNOM] Connexion à Firestore établie")
        
        # Récupérer tous les tokens depuis la collection 'fcm_tokens'
        logger.info("📂 [ENVOI À TOUS AVEC PRÉNOM] Récupération des tokens depuis la collection 'fcm_tokens'...")
        tokens_snapshot = db.collection('fcm_tokens').get()
        
        logger.info(f"📊 [ENVOI À TOUS AVEC PRÉNOM] Nombre de documents trouvés: {len(tokens_snapshot)}")
        
        if not tokens_snapshot:
            logger.warning("⚠️ [ENVOI À TOUS AVEC PRÉNOM] Aucun token FCM trouvé dans Firestore")
            return {'successCount': 0, 'failureCount': 0, 'totalTokens': 0}
        
        notifications = []  # Liste de {token, userId, prenom}
        valid_tokens = 0
        invalid_tokens = 0
        
        logger.info("🔍 [ENVOI À TOUS AVEC PRÉNOM] Extraction des tokens et userIds depuis les documents...")
        for doc in tokens_snapshot:
            token_data = doc.to_dict()
            user_id = doc.id
            
            if token_data.get('token'):
                notifications.append({
                    'token': token_data['token'],
                    'userId': user_id,
                    'prenom': token_data.get('prenom'),
                })
                valid_tokens += 1
                logger.info(f"   ✅ Token valide trouvé pour userId: {user_id} (prénom: {token_data.get('prenom', 'non disponible')})")
            else:
                invalid_tokens += 1
                logger.warning(f"   ⚠️ Document sans token pour userId: {user_id}")
        
        logger.info(f"📱 [ENVOI À TOUS AVEC PRÉNOM] Résumé de l'extraction:")
        logger.info(f"   - Tokens valides: {valid_tokens}")
        logger.info(f"   - Tokens invalides: {invalid_tokens}")
        logger.info(f"   - Total notifications à envoyer: {len(notifications)}")
        
        if not notifications:
            logger.error("❌ [ENVOI À TOUS AVEC PRÉNOM] Aucun token valide trouvé, arrêt du processus")
            return {'successCount': 0, 'failureCount': 0, 'totalTokens': 0}
        
        # Récupérer les prénoms depuis la collection users pour ceux qui n'ont pas de prénom dans fcm_tokens
        logger.info("👤 [ENVOI À TOUS AVEC PRÉNOM] Récupération des prénoms depuis la collection 'users'...")
        users_to_fetch = [n for n in notifications if not n.get('prenom')]
        
        if users_to_fetch:
            logger.info(f"   📋 Récupération des prénoms pour {len(users_to_fetch)} utilisateurs...")
            
            # Récupérer les prénoms par batch
            batch_size = 10
            for i in range(0, len(users_to_fetch), batch_size):
                batch = users_to_fetch[i:i + batch_size]
                for notification in batch:
                    try:
                        user_id = notification['userId']
                        user_doc = db.collection('users').document(user_id).get()
                        if user_doc.exists:
                            user_data = user_doc.to_dict()
                            prenom = user_data.get('prenom')
                            notification['prenom'] = prenom
                    except Exception as error:
                        logger.error(f"   ❌ Erreur lors de la récupération du prénom pour {notification['userId']}: {error}")
            
            logger.info(f"   ✅ Prénoms récupérés pour {len(users_to_fetch)} utilisateurs")
        
        # Envoyer les notifications personnalisées
        logger.info("📤 [ENVOI À TOUS AVEC PRÉNOM] Envoi des notifications personnalisées via FCM...")
        success_count = 0
        failure_count = 0
        
        # Envoyer les notifications une par une pour pouvoir personnaliser
        for notification in notifications:
            try:
                # Personnaliser le titre et le corps avec le prénom (chaîne vide si anonyme ou non trouvé)
                prenom = notification.get('prenom') or ''
                personalized_title = title_template.replace('{prenom}', prenom)
                personalized_body = body_template.replace('{prenom}', prenom)
                
                display_name = notification.get('prenom') or notification.get('userId') or 'anonyme'
                logger.info(f"   📨 Envoi à {display_name}: \"{personalized_title}\"")
                
                send_push_notification(
                    notification['token'],
                    personalized_title,
                    personalized_body,
                    data
                )
                
                success_count += 1
            except Exception as error:
                display_name = notification.get('prenom') or notification.get('userId') or 'anonyme'
                logger.error(f"   ❌ Échec pour {display_name}: {error}")
                failure_count += 1
        
        logger.info("📊 [ENVOI À TOUS AVEC PRÉNOM] Résultats de l'envoi:")
        logger.info(f"   ✅ Notifications envoyées avec succès: {success_count}")
        logger.info(f"   ❌ Notifications échouées: {failure_count}")
        logger.info(f"   📱 Total de notifications traitées: {len(notifications)}")
        
        result = {
            'successCount': success_count,
            'failureCount': failure_count,
            'totalTokens': len(notifications),
        }
        
        logger.info("✅ [ENVOI À TOUS AVEC PRÉNOM] Processus terminé avec succès")
        return result
    except Exception as error:
        logger.error(f"❌ [ENVOI À TOUS AVEC PRÉNOM] Erreur lors de l'envoi à tous: {error}")
        raise


def send_push_notification_to_group(user_ids, title, body, data=None):
    """
    Envoie une notification à un groupe d'utilisateurs spécifiques
    
    Args:
        user_ids (list): Liste des userIds des utilisateurs
        title (str): Le titre de la notification
        body (str): Le corps de la notification
        data (dict): Données supplémentaires (optionnel)
    
    Returns:
        dict: Résultat avec successCount et failureCount
    """
    try:
        get_firebase_app()
        from firebase_admin import firestore
        
        logger.info(f"👥 [ENVOI À GROUPE] Début pour {len(user_ids)} utilisateurs")
        logger.info(f"📝 [ENVOI À GROUPE] Titre: \"{title}\"")
        logger.info(f"📝 [ENVOI À GROUPE] Corps: \"{body}\"")
        
        db = firestore.client()
        
        # Récupérer les tokens pour les userIds spécifiés
        logger.info("🔍 [ENVOI À GROUPE] Récupération des tokens depuis Firestore...")
        tokens = []
        invalid_users = []
        
        for user_id in user_ids:
            try:
                token_doc = db.collection('fcm_tokens').document(user_id).get()
                
                if token_doc.exists:
                    token_data = token_doc.to_dict()
                    token = token_data.get('token')
                    
                    if token:
                        tokens.append(token)
                        logger.info(f"   ✅ Token trouvé pour userId: {user_id}")
                    else:
                        invalid_users.append(user_id)
                        logger.warning(f"   ⚠️ Token vide pour userId: {user_id}")
                else:
                    invalid_users.append(user_id)
                    logger.warning(f"   ⚠️ Aucun document trouvé pour userId: {user_id}")
            except Exception as error:
                invalid_users.append(user_id)
                logger.error(f"   ❌ Erreur pour userId {user_id}: {error}")
        
        logger.info(f"📊 [ENVOI À GROUPE] Résumé:")
        logger.info(f"   - Tokens valides: {len(tokens)}")
        logger.info(f"   - Utilisateurs invalides: {len(invalid_users)}")
        
        if not tokens:
            logger.error("❌ [ENVOI À GROUPE] Aucun token valide trouvé")
            return {
                'successCount': 0,
                'failureCount': len(user_ids),
                'totalTokens': 0,
                'invalidUsers': invalid_users,
            }
        
        # Envoyer les notifications via multicast
        logger.info("📤 [ENVOI À GROUPE] Envoi des notifications via FCM...")
        response = send_push_notification_to_multiple(tokens, title, body, data)
        
        logger.info("📊 [ENVOI À GROUPE] Résultats de l'envoi:")
        logger.info(f"   ✅ Notifications envoyées avec succès: {response['successCount']}")
        logger.info(f"   ❌ Notifications échouées: {response['failureCount']}")
        
        result = {
            'successCount': response['successCount'],
            'failureCount': response['failureCount'] + len(invalid_users),
            'totalTokens': len(tokens),
            'invalidUsers': invalid_users if invalid_users else None,
        }
        
        logger.info("✅ [ENVOI À GROUPE] Processus terminé")
        return result
    except Exception as error:
        logger.error(f"❌ [ENVOI À GROUPE] Erreur lors de l'envoi au groupe: {error}")
        raise

