FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY frontend/ ./frontend/

WORKDIR /app/frontend

EXPOSE 7860

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "7860"]
