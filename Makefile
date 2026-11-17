.PHONY: install demo api front test docker

install:
	pip install -r requirements.txt
	cd frontend && npm install

demo:          ## données de démo + features + entraînement + scoring
	python -m aeroops.cli demo

api:
	uvicorn aeroops.api.main:app --reload --port 8000

front:
	cd frontend && npm run dev

test:
	python -m pytest -q

docker:
	docker compose up --build
