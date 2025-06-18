.PHONY: build up down logs worker api test clean

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

worker:
	docker-compose run --rm worker

api:
	docker-compose run --rm api

test:
	python test_refactored.py

clean:
	rm -rf temp/uploads/* temp/results/* logs/* 