FROM python:3.13-slim
WORKDIR /app
COPY requirements-mobile.lock ./
RUN pip install --no-cache-dir -r requirements-mobile.lock
RUN useradd --create-home --uid 10001 orthoflow && mkdir /data && chown orthoflow:orthoflow /data
COPY mobile ./mobile
COPY ai_ocr.py document_compression.py ./
USER orthoflow
ENV MOBILE_DATA_DIR=/data
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn mobile.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
