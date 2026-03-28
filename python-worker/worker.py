import os
import time
import random
import logging
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
from redis import Redis
from urllib.parse import urlparse

# Load .env from the tox-backend root (parent of python-worker/)
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── Config from env ────────────────────────────────────────────────────────
REDIS_URL    = os.environ["UPSTASH_REDIS_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
STREAM_NAME  = "llm_task_queue"
CONSUMER_GRP = "python-llm-workers"
CONSUMER_ID  = f"worker-{os.getpid()}"
PUBSUB_CHAN  = "job_completed_events"

# ── Model pipeline (loaded once at startup) ────────────────────────────────
_PIPELINE_PATH = Path(__file__).parent / "toxicity_model.pkl"
_pipeline      = None  # populated in run()


def _load_model() -> object | None:
    """Load the trained pipeline. Returns None if pkl not found."""
    import model as tox_model  # local model.py
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
    return Redis(
        host=parsed.hostname,
        port=parsed.port,
        password=parsed.password,
        ssl=True,
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
    """Fallback mock — used when toxicity_model.pkl is absent."""
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
    """Route inference to the real model or fall back to mock."""
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

    # Load model once at startup
    _pipeline = _load_model()

    rdb = make_redis()
    ensure_consumer_group(rdb)

    while True:
        try:
            entries = rdb.xreadgroup(
                groupname=CONSUMER_GRP,
                consumername=CONSUMER_ID,
                streams={STREAM_NAME: ">"},
                count=1,
                block=5000,
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
                smiles  = fields.get("smiles", "")
                log.info(f"📥 Received job {job_id} | SMILES: {smiles[:30]}...")

                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE predictions SET status = 'processing' WHERE id = %s",
                                (job_id,)
                            )
                        conn.commit()

                    result = predict_toxicity(smiles)

                    update_prediction(
                        job_id,
                        result["tox_score"],
                        result["tox_class"],
                        result["llm_explanation"],
                    )

                    rdb.publish(PUBSUB_CHAN, job_id)
                    log.info(f"📡 Published completion event for job {job_id}")

                except Exception as exc:
                    log.exception(f"❌ Inference failed for job {job_id}: {exc}")
                    mark_failed(job_id, str(exc))

                finally:
                    rdb.xack(STREAM_NAME, CONSUMER_GRP, msg_id)


if __name__ == "__main__":
    run()
