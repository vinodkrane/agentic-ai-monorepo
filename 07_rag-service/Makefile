.PHONY: install up down setup seed api worker test eval-retrieval eval-llm eval-latency lint worker-image push-worker deploy-ingest

ENV ?= dev
AWS_REGION ?= eu-west-2
ACCOUNT_ID ?= $(shell aws sts get-caller-identity --query Account --output text)
ECR_REPO = $(ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/kb-rag-worker
TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)

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

# same worker that runs on EC2, pointed at localstack via .env
worker:
	python -m app.ingest.worker

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

worker-image:
	docker build -f Dockerfile.worker -t kb-rag-worker:$(TAG) .

push-worker: worker-image
	aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_REPO)
	docker tag kb-rag-worker:$(TAG) $(ECR_REPO):$(TAG)
	docker push $(ECR_REPO):$(TAG)
	@echo "pushed $(ECR_REPO):$(TAG)"

# needs SUBNETS, SG and OPENSEARCH_HOST / OPENSEARCH_ARN set, see README
deploy-ingest:
	aws cloudformation deploy --template-file infra/template.yaml \
	  --stack-name kb-rag-ingest-$(ENV) --capabilities CAPABILITY_NAMED_IAM \
	  --parameter-overrides Env=$(ENV) WorkerImage=$(ECR_REPO):$(TAG) \
	    SubnetIds=$(SUBNETS) WorkerSecurityGroupId=$(SG) \
	    OpenSearchHost=$(OPENSEARCH_HOST) OpenSearchDomainArn=$(OPENSEARCH_ARN)
