# --- étape 1 : build du front React
FROM node:22-alpine AS front
WORKDIR /front
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- étape 2 : API Python + front compilé
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN grep -v "^-e" requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt
COPY src/ src/
COPY sql/ sql/
COPY --from=front /front/dist frontend/dist
EXPOSE 8000
# Au premier démarrage, génère les données de démo et entraîne les modèles si besoin
CMD ["sh", "-c", "[ -f models/meta.json ] || python -m aeroops.cli demo; uvicorn aeroops.api.main:app --host 0.0.0.0 --port 8000"]
