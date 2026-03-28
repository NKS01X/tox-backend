# Python Worker: Toxicity Model

This directory contains the Python worker microservice and the machine learning pipeline for toxicity detection. The worker processes SMILES strings from the Go backend via Redis Streams, performs toxicity inference using an ensemble model (LightGBM + XGBoost), and updates the PostgreSQL database.

## Prerequisites

- Python 3.10+
- Upstash Redis and PostgreSQL (configured in `.env` at the root of `tox-backend`)

## Setup

1. **Create and activate a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure Environment:**
Copy `.env.example` to `.env` in the root `tox-backend` directory and add your `UPSTASH_REDIS_URL` and `DATABASE_URL`.

## Training the Model

The worker features a graceful fallback mock if the real model is missing. To use real inference, you must generate `toxicity_model.pkl`.

```bash
# Provide the path to your tox21.csv dataset
python train.py --csv /path/to/tox21.csv
```
This script handles the full pipeline:
- Extracts RDKit features (Morgan fingerprints & continuous descriptors)
- Filters features by variance threshold
- Trains an ensemble of LightGBM and XGBoost models
- Outputs `toxicity_model.pkl` to the current directory

## Running the Worker

Once the environment is set and the model is trained, start the worker:

```bash
python worker.py
```

The worker will automatically connect to your Redis and Postgres instances. It continuously consumes tasks from the `llm_task_queue` stream, performs inference (falling back to mock data if `toxicity_model.pkl` is absent), updates Postgres, and publishes completion events to Redis Pub/Sub (`job_completed_events`).
