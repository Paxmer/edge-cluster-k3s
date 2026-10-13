# Construir desde la RAIZ del kit (necesita artifacts/model.joblib, generado con python train.py):
#   docker buildx build --platform linux/amd64 -f service/Dockerfile \
#       -t edge-infer:1.0 -o type=docker,dest=edge-infer.tar .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY service/requirements.txt service/requirements.txt
RUN pip install --no-cache-dir -r service/requirements.txt

COPY edgekit/ edgekit/
COPY service/ service/
COPY artifacts/model.joblib artifacts/model.joblib

ENV PORT=8000
EXPOSE 8000
USER 1000
CMD ["python", "-m", "service.app"]
