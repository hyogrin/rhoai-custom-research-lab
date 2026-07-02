FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/ ./backend/
COPY harness/ ./harness/
COPY agents/ ./agents/
COPY config/ ./config/

EXPOSE 8000

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
