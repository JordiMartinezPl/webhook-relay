.PHONY: dev stop

dev:
	docker compose up -d
	tmux new-session -d -s webhook-relay 'bash -c "source venv/bin/activate && python manage.py runserver; exec bash"'
	tmux split-window -t webhook-relay 'bash -c "source venv/bin/activate && celery -A config worker --loglevel=info; exec bash"'
	tmux attach -t webhook-relay

stop:
	-tmux kill-session -t webhook-relay
	docker compose down
