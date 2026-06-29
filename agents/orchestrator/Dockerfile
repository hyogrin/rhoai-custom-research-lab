FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir kagenti-adk langgraph httpx openai python-dotenv

EXPOSE 8100

CMD ["python", "agent.py"]
