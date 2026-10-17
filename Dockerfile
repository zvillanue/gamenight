FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Runs as 1000:1000 (see docker-compose.yml) so bind-mounted ./instance stays
# owned by the host's normal user, same convention as obsidian-store.
EXPOSE 8000

# SQLite allows one writer at a time; a few workers is plenty for a friend group.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-2} --access-logfile - wsgi:app"]
