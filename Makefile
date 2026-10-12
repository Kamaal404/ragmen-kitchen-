.DEFAULT_GOAL := help
SHELL := /bin/bash

PROFILE ?= legal
INPUT   ?=
CHUNKS  ?= chunks.jsonl
GRAPH   ?= graph.jsonl
LIMIT   ?= 10
Q       ?= obligations of the employer
TOPK    ?= 5
SCHEMA  ?= vendor/blueprint/blueprint.schema.json

PY := PYTHONPATH=src $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3) -m ragmen.cli

set_env = set -a; [ -f .env ] && source .env; set +a;

.PHONY: help setup up down logs shell reset test toss cook dry load query validate serve tags

help:
	@echo "RAGmen Kitchen"
	@echo ""
	@echo "  make test                     offline test suite (no LLM, no DB)"
	@echo ""
	@echo "  make toss     PROFILE=legal   validate an approved blueprint"
	@echo "  make cook     PROFILE=legal   segment + extract + dry run"
	@echo "  make load     PROFILE=legal   write extracted graph to Neo4j"
	@echo "  make query    PROFILE=legal   one-shot cited answer"
	@echo "  make serve                   start read-only MCP server"
	@echo "  make validate PROFILE=legal   validate ingested graph"
	@echo ""
	@echo "  make up / down / shell        Neo4j container"
	@echo ""
	@echo "current: PROFILE=$(PROFILE) INPUT=$(INPUT)"

test:
	PYTHONPATH=src python -m pytest -q --tb=short -m "not integration"

toss:
	$(PY) toss vendor/blueprint/test-vectors/valid/minimal.yaml --verbose

cook:
	@test -n "$(INPUT)" || { echo "set INPUT=/path/to/corpus"; exit 2; }
	$(PY) cook --profile $(PROFILE) --input $(INPUT) --chunks $(CHUNKS) --graph $(GRAPH) --limit $(LIMIT)

dry: cook

load:
	@$(set_env) $(PY) cook --profile $(PROFILE) --input $(INPUT) --write

query:
	$(PY) query --profile $(PROFILE) --top-k $(TOPK) "$(Q)"

serve:
	$(PY) serve

validate:
	@$(set_env) $(PY) -c "from ragmen.cook.validate import main; main()"

up:
	docker compose up -d

down:
	docker compose down

shell:
	@$(set_env) docker compose exec neo4j cypher-shell -u $$NEO4J_USER -p $$NEO4J_PASSWORD

reset:
	docker compose down -v && docker compose up -d