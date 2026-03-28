FROM python:3.10-slim

WORKDIR /app

# Install system dependencies required by RDKit and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY worker.py model.py train.py ./

# Copy pre-trained model if it exists (optional — worker falls back to mock if absent)
COPY toxicity_model.pkl ./

CMD ["python", "worker.py"]
