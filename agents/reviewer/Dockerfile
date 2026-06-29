FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir kagenti-adk langgraph openai python-dotenv

EXPOSE 8104

CMD ["python", "agent.py"]
