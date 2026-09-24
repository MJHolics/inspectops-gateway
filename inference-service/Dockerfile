FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py model.onnx ./
EXPOSE 8000
# K8s에서는 WORKERS=1로 파드당 1프로세스 — 확장은 HPA(파드 수)로 한다
ENV WORKERS=2
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port 8000 --workers ${WORKERS}"]
