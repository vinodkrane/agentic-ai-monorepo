.PHONY: install up down setup seed api worker test eval-retrieval eval-llm eval-latency lint lambda-zip

install:
	pip install -r requirements-dev.txt

up:
	docker compose up -d

down:
	docker compose down

setup:
	bash scripts/localstack_setup.sh

seed:
	bash scripts/seed_local.sh

api:
	uvicorn app.api:app --reload --port 8000

# local replacement for the SQS -> lambda trigger
worker:
	python -m scripts.poll_queue

test:
	pytest -m "not llm"

eval-retrieval:
	pytest evals/test_regression.py -m "not llm" -v -s

eval-llm:
	pytest evals/test_deepeval.py evals/test_safety.py evals/test_regression.py -v

eval-latency:
	python -m evals.latency --runs 3

lint:
	ruff check app evals tests scripts

lambda-zip:
	rm -rf build && mkdir -p build/pkg
	pip install -r requirements-lambda.txt -t build/pkg --platform manylinux2014_x86_64 --only-binary=:all:
	cp -r app build/pkg/
	cd build/pkg && zip -qr ../ingest.zip .
	@echo "build/ingest.zip"
