# 📍 Emplacement du fichier serviceAccountKey.json

## Chemin exact

Le fichier `serviceAccountKey.json` doit être placé dans :

```
butter_web_interface/media/input/serviceAccountKey.json
```

## Chemin relatif depuis la racine du projet

```
media/input/serviceAccountKey.json
```

## Configuration dans le code

Le chemin est défini dans `scripts_manager/config.py` :

```python
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MEDIA_ROOT = BASE_DIR / 'media'
INPUT_DIR = MEDIA_ROOT / "input"
SERVICE_ACCOUNT_PATH = str(INPUT_DIR / "serviceAccountKey.json")
```

## Commandes pour créer le dossier et placer le fichier

### Sur votre machine locale

```bash
cd /Users/admin/Documents/butter_web_interface
mkdir -p media/input
# Copier votre fichier
cp /chemin/vers/votre/serviceAccountKey.json media/input/serviceAccountKey.json
```

### Sur le serveur OVH

```bash
cd ~/butter-gestion
mkdir -p media/input
# Puis utilisez scp depuis votre machine locale :
# scp input/serviceAccountKey.json znwbmgq@ssh02.cluster100.gra.hosting.ovh.net:~/butter-gestion/media/input/
```

## Vérification

```bash
# Vérifier que le fichier existe
ls -la media/input/serviceAccountKey.json

# Vérifier le contenu (doit être un JSON valide)
head -5 media/input/serviceAccountKey.json
```

## Structure des dossiers

```
butter_web_interface/
├── media/                    ← Dossier créé automatiquement
│   ├── input/               ← Dossier pour les fichiers d'entrée
│   │   └── serviceAccountKey.json  ← VOTRE FICHIER ICI
│   └── exports/             ← Dossier pour les exports Excel
├── scripts_manager/
│   └── config.py           ← Configuration du chemin
└── ...
```

## Important

- Le dossier `media/` est créé automatiquement par Django
- Le dossier `input/` est créé automatiquement par `config.py`
- Le fichier `serviceAccountKey.json` doit être ajouté manuellement
- Ce fichier est dans `.gitignore` et ne sera pas commité

## Où obtenir le fichier serviceAccountKey.json ?

1. Allez sur [Firebase Console](https://console.firebase.google.com/)
2. Sélectionnez votre projet
3. Allez dans **Paramètres du projet** (icône ⚙️)
4. Onglet **Comptes de service**
5. Cliquez sur **Générer une nouvelle clé privée**
6. Téléchargez le fichier JSON
7. Renommez-le en `serviceAccountKey.json`
8. Placez-le dans `media/input/`



