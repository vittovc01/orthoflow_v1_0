FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
# Snapshot freezes Debian packages as well as the Tesseract engine/trained data.
RUN printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260801T000000Z bookworm main\n' > /etc/apt/sources.list \
 && rm -f /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgomp1 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-ocr.lock .
RUN pip install --no-cache-dir -r requirements-ocr.lock
COPY . .
ENV OCR_REVIEW_ARCHIVE_ENABLED=false PYTHONUNBUFFERED=1
RUN python scripts/check_ocr_runtime.py
ENTRYPOINT ["python", "evaluate_ocr.py"]
