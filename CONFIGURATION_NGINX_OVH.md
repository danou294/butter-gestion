# 🌐 Configuration Nginx pour OVH

Guide pour configurer Nginx comme reverse proxy pour exposer l'application sur le port 80.

## Option 1 : Reverse Proxy Nginx (Recommandé)

### 1. Vérifier si Nginx est installé

```bash
nginx -v
```

Si Nginx n'est pas installé, contactez le support OVH ou installez-le selon votre plan d'hébergement.

### 2. Créer la configuration Nginx

Créez un fichier de configuration pour votre application :

```bash
sudo nano /etc/nginx/sites-available/butter-gestion
```

Ou si vous n'avez pas les droits sudo, créez dans votre home :

```bash
mkdir -p ~/nginx-config
nano ~/nginx-config/butter-gestion.conf
```

### 3. Configuration Nginx

```nginx
server {
    listen 80;
    server_name votre-domaine.com;  # Remplacez par votre domaine ou IP

    # Taille maximale des uploads
    client_max_body_size 50M;

    # Fichiers statiques (si collectstatic a été fait)
    location /static/ {
        alias /home/znwbmgq/butter-gestion/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Fichiers média
    location /media/ {
        alias /home/znwbmgq/butter-gestion/media/;
        expires 30d;
        add_header Cache-Control "public";
    }

    # Proxy vers l'application Django
    location / {
        proxy_pass http://127.0.0.1:8000;  # Port interne
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### 4. Activer la configuration

**Avec sudo :**
```bash
sudo ln -s /etc/nginx/sites-available/butter-gestion /etc/nginx/sites-enabled/
sudo nginx -t  # Tester la configuration
sudo systemctl reload nginx
```

**Sans sudo (configuration personnalisée) :**
Vous devrez peut-être contacter le support OVH pour activer cette configuration.

### 5. Démarrer Django sur le port interne

```bash
cd ~/butter-gestion
source venv/bin/activate

# Option A : Serveur de développement (test uniquement)
python manage.py runserver 127.0.0.1:8000

# Option B : Gunicorn (production)
gunicorn butter_web_interface.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

## Option 2 : Autoriser le port 8000 dans le firewall OVH

### Via le panneau OVH

1. Connectez-vous à votre [espace client OVH](https://www.ovh.com/manager/)
2. Allez dans **IP** → **Firewall**
3. Ajoutez une règle pour autoriser le port 8000 (TCP)
4. Appliquez les modifications

### Via SSH (si vous avez les droits)

```bash
# Vérifier les règles firewall actuelles
sudo iptables -L -n

# Autoriser le port 8000 (si iptables est utilisé)
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT

# Sauvegarder les règles (selon votre système)
sudo iptables-save
```

**Note** : Sur OVH, le firewall est généralement géré via le panneau web, pas directement en SSH.

## Option 3 : Utiliser Gunicorn directement sur le port 80

⚠️ **Nécessite les privilèges root** (peut ne pas être possible sur OVH)

```bash
cd ~/butter-gestion
source venv/bin/activate
pip install gunicorn

# Nécessite sudo (peut ne pas fonctionner)
sudo gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:80 --workers 4
```

## Option 4 : Utiliser un port alternatif accessible

Si vous ne pouvez pas utiliser le port 80, utilisez un port standard autorisé :

```bash
# Port 8080 (généralement autorisé)
python manage.py runserver 0.0.0.0:8080

# Ou avec Gunicorn
gunicorn butter_web_interface.wsgi:application --bind 0.0.0.0:8080 --workers 4
```

Puis accédez à `http://VOTRE_IP:8080`

## Configuration recommandée pour production

### 1. Installer Gunicorn

```bash
source venv/bin/activate
pip install gunicorn
```

### 2. Créer un fichier de configuration Gunicorn

```bash
nano ~/butter-gestion/gunicorn_config.py
```

Contenu :

```python
bind = "127.0.0.1:8000"
workers = 4
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
```

### 3. Démarrer avec Gunicorn

```bash
cd ~/butter-gestion
source venv/bin/activate
gunicorn -c gunicorn_config.py butter_web_interface.wsgi:application
```

### 4. Démarrer en arrière-plan

```bash
nohup gunicorn -c gunicorn_config.py butter_web_interface.wsgi:application > gunicorn.log 2>&1 &
```

### 5. Vérifier que ça fonctionne

```bash
# Vérifier les processus
ps aux | grep gunicorn

# Vérifier les logs
tail -f gunicorn.log

# Tester l'accès
curl http://127.0.0.1:8000
```

## Script de démarrage automatique

Créez un script pour démarrer facilement :

```bash
nano ~/butter-gestion/start.sh
```

Contenu :

```bash
#!/bin/bash
cd ~/butter-gestion
source venv/bin/activate
gunicorn -c gunicorn_config.py butter_web_interface.wsgi:application --bind 127.0.0.1:8000 --workers 4 --daemon
echo "Serveur démarré sur http://127.0.0.1:8000"
```

Rendre exécutable :

```bash
chmod +x ~/butter-gestion/start.sh
```

## Vérification

### Tester l'accès local

```bash
curl http://127.0.0.1:8000
```

### Tester depuis l'extérieur

```bash
# Depuis votre machine locale
curl http://VOTRE_IP_OVH:8000
```

### Vérifier les ports ouverts

```bash
netstat -tuln | grep LISTEN
```

## Dépannage

### Erreur : "Address already in use"

Le port est déjà utilisé. Trouvez le processus :

```bash
lsof -i :8000
# ou
netstat -tuln | grep 8000
```

Arrêtez le processus ou utilisez un autre port.

### Erreur : "Permission denied"

Vous n'avez pas les droits pour utiliser le port. Utilisez un port > 1024 ou contactez le support OVH.

### Nginx ne redirige pas correctement

Vérifiez les logs Nginx :

```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

---

**Recommandation** : Utilisez Nginx en reverse proxy (Option 1) pour une configuration de production propre et sécurisée.

