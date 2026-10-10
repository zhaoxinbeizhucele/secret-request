FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY secret_request ./secret_request
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SECRET_REQUEST_CONFIG=/run/config/relay.json
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "secret_request.relay:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8787", "--workers", "1", "--no-access-log", "--log-level", "warning"]
