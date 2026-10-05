FROM python:3.13-slim
WORKDIR /app
COPY requirements-unified.lock ./
RUN pip install --no-cache-dir -r requirements-unified.lock && pip check
RUN useradd --create-home --uid 10001 orthoflow && mkdir /data && chown orthoflow:orthoflow /data
COPY . ./
RUN mkdir -p /data/uploads /data/legacy \
    && rm -rf /app/uploads /app/data \
    && ln -s /data/uploads /app/uploads \
    && ln -s /data/legacy /app/data \
    && chown -R orthoflow:orthoflow /data
USER orthoflow
ENV MOBILE_DATA_DIR=/data
EXPOSE 8000
CMD ["python", "-m", "mobile.serve"]
