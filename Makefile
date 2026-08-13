.PHONY: dev stop

dev:
	docker compose up --build

stop:
	docker compose down
