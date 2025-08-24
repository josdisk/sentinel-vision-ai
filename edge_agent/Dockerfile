FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libsm6 libxext6 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /agent
COPY edge_agent/requirements.txt /agent/requirements.txt
RUN pip install --no-cache-dir -r /agent/requirements.txt
COPY edge_agent /agent
ENV PYTHONUNBUFFERED=1
CMD ["python","agent.py"]
