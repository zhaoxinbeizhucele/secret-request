FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY secret_request ./secret_request
# Source archives may have been extracted with a private umask. The unprivileged
# server must be able to traverse package directories and serve static files.
RUN chmod -R a+rX /app/secret_request
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SECRET_REQUEST_CONFIG=/run/config/relay.json
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)"]
CMD ["python", "-m", "secret_request.server"]
