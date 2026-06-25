# 1. Utiliser une image Python officielle et légère
FROM python:3.11-slim

# 2. Définir le dossier de travail dans le conteneur
WORKDIR /app

# 3. Installer les dépendances système nécessaires si besoin (gestion des certificats, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. Copier d'abord le requirements.txt pour optimiser le cache Docker
COPY requirements.txt .

# 5. Installer les bibliothèques Python
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copier tout le reste du code du dossier local dans le conteneur
COPY . .

# 7. Exposer le port sur lequel ton FastAPI va écouter (8001 pour l'orchestrateur)
EXPOSE 8001

# 8. Commande pour lancer l'API avec Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]