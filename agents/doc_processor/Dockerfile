FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir kagenti-adk langgraph docling psycopg2-binary openai python-dotenv

EXPOSE 8101

CMD ["python", "agent.py"]
