"""
worker.py — Redis queue consumer for Tox21 inference
"""

import os
import time
import random
import logging
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
from redis import Redis
from urllib.parse import urlparse

# Load .env from the tox-backend root
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config from env ────────────────────────────────────────────────────────
REDIS_URL    = os.environ.get("UPSTASH_REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.environ.get("DATABASE_URL")
STREAM_NAME  = "llm_task_queue"
CONSUMER_GRP = "python-llm-workers"
CONSUMER_ID  = f"worker-{os.getpid()}"
PUBSUB_CHAN  = "job_completed_events"

# ── Model pipeline ─────────────────────────────────────────────────────────
_PIPELINE_PATH = Path(__file__).parent / "toxicity_model.pkl"
_pipeline      = None  

def _load_model() -> object | None:
    import model as tox_model 
    if _PIPELINE_PATH.exists():
        try:
            pipeline = tox_model.load_pipeline(str(_PIPELINE_PATH))
            log.info("🧪 Real toxicity model loaded successfully")
            return pipeline
        except Exception as exc:
            log.error(f"Failed to load model pipeline: {exc}")
    else:
        log.warning(
            f"⚠️  {_PIPELINE_PATH.name} not found — using mock inference. "
            "Run: python train.py --csv /path/to/tox21.csv"
        )
    return None

# ── Redis client ───────────────────────────────────────────────────────────
def make_redis() -> Redis:
    parsed = urlparse(REDIS_URL)
    # Note: If testing locally without SSL, you may need to set ssl=False depending on your Upstash/Redis setup
    is_secure = parsed.scheme == "rediss"
    return Redis(
        host=parsed.hostname, 
        port=parsed.port or 6379, 
        password=parsed.password,
        ssl=is_secure, 
        decode_responses=True,
    )

# ── PostgreSQL helpers ─────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def update_prediction(job_id: str, tox_score: float, tox_class: str, explanation: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE predictions
                SET status          = 'completed',
                    tox_score       = %s,
                    tox_class       = %s,
                    llm_explanation = %s
                WHERE id = %s
                """,
                (tox_score, tox_class, explanation, job_id),
            )
        conn.commit()
    log.info(f"✅ Updated job {job_id} in DB")

def mark_failed(job_id: str, reason: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE predictions SET status = 'failed', llm_explanation = %s WHERE id = %s",
                (reason, job_id),
            )
        conn.commit()
    log.warning(f"⚠️  Marked job {job_id} as failed: {reason}")

# ── Inference ──────────────────────────────────────────────────────────────
def _predict_mock(smiles: str) -> dict:
    time.sleep(0.5)
    score = round(random.uniform(0.0, 1.0), 4)
    if score < 0.25:
        cls = "Non-toxic"
        expl = f"[MOCK] {smiles[:20]}… very low toxicity (score {score})."
    elif score < 0.50:
        cls = "Low"
        expl = f"[MOCK] {smiles[:20]}… low toxicity (score {score}). Monitor dosage."
    elif score < 0.75:
        cls = "Moderate"
        expl = f"[MOCK] {smiles[:20]}… moderate toxicity (score {score}). Handle with care."
    else:
        cls = "High"
        expl = f"[MOCK] {smiles[:20]}… high toxicity (score {score}). Hazardous."
    return {"tox_score": score, "tox_class": cls, "llm_explanation": expl}

def predict_toxicity(smiles: str) -> dict:
    if _pipeline is not None:
        import model as tox_model
        return tox_model.predict_toxicity(smiles, _pipeline)
    return _predict_mock(smiles)

# ── Consumer loop ──────────────────────────────────────────────────────────
def ensure_consumer_group(rdb: Redis):
    try:
        rdb.xgroup_create(STREAM_NAME, CONSUMER_GRP, id="0", mkstream=True)
        log.info(f"Created consumer group '{CONSUMER_GRP}'")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            log.info(f"Consumer group '{CONSUMER_GRP}' already exists")
        else:
            raise

def run():
    global _pipeline
    log.info(f"🐍 Python worker starting (pid={os.getpid()})")

    _pipeline = _load_model()
    rdb = make_redis()
    ensure_consumer_group(rdb)

    while True:
        try:
            entries = rdb.xreadgroup(
                groupname=CONSUMER_GRP, consumername=CONSUMER_ID,
                streams={STREAM_NAME: ">"}, count=1, block=5000,
            )
        except Exception as e:
            log.error(f"Redis read error, retrying in 2s: {e}")
            time.sleep(2)
            continue

        if not entries:
            continue

        for stream, messages in entries:
            for msg_id, fields in messages:
                job_id = fields.get("job_id")
                smiles = fields.get("smiles", "")
                log.info(f"📥 Received job {job_id} | SMILES: {smiles[:30]}...")

                try:
                    # 1. Mark as processing
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE predictions SET status = 'processing' WHERE id = %s", (job_id,))
                        conn.commit()

                    # 2. Run inference (Will raise ValueError if SMILES is invalid)
                    result = predict_toxicity(smiles)

                    # 3. Update DB to completed
                    update_prediction(
                        job_id, result["tox_score"], result["tox_class"], result["llm_explanation"]
                    )

                    # 4. Notify WebSocket that the job succeeded
                    rdb.publish(PUBSUB_CHAN, job_id)
                    log.info(f"📡 Published completion event for job {job_id}")

                except Exception as exc:
                    log.exception(f"❌ Inference failed for job {job_id}: {exc}")
                    
                    # 1. Update DB to failed
                    mark_failed(job_id, str(exc))
                    
                    # 2. [FIX] Notify WebSocket that the job failed, preventing infinite hangs
                    rdb.publish(PUBSUB_CHAN, job_id)
                    log.info(f"📡 Published FAILURE event for job {job_id} to prevent WebSocket hang")

                finally:
                    # Always ack the message so it doesn't get stuck in the pending list
                    rdb.xack(STREAM_NAME, CONSUMER_GRP, msg_id)

if __name__ == "__main__":
    run()