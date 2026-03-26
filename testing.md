# 🧪 Tox-Detector Testing Guide

This guide walks you through the process of testing the full automated flow: from user registration and login, to submitting a chemical SMILES string, and receiving a real-time toxicity prediction from the Python LLM worker.

## 1. Prerequisites & Setup

Ensure your `.env` contains:
- `UPSTASH_REDIS_URL`
- `DATABASE_URL` (Supabase Postgres)
- `JWT_SECRET`
- `SUPABASE_JWT_SECRET`

### Start the Go Backend
```bash
go run main.go
```

### Start the Python Worker
```bash
cd python-worker
venv/bin/python worker.py
```

---

## 2. Authentication Flow

### A. Signup
Create a new account manually:
```bash
curl -X POST http://localhost:8080/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email": "tox_tester@example.com", "password": "password123"}'
```

### B. Login
Get your JWT token:
```bash
curl -X POST http://localhost:8080/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "tox_tester@example.com", "password": "password123"}'
```
*Copy the `"token"` value from the response.*

---

## 3. Toxicity Prediction Flow

### A. Ingest a SMILES Job
Replace `<TOKEN>` with your JWT:
```bash
curl -X POST http://localhost:8080/v1/api/jobs \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O"}'
```
**Expected Response:** `{"job_id": "...", "status": "queued"}`

### B. Wait for Real-Time Result (WebSocket)
Connect to the WebSocket to see the automated worker response. Use `wscat` or a similar tool:
```bash
# Replace <JOB_ID> with the ID from Step A
wscat -c ws://localhost:8080/v1/api/jobs/ws/<JOB_ID>
```

**What happens next:**
1. Your request is in the Redis Stream.
2. The **Python Worker** detects it, runs the (mock) toxicity model, and updates Supabase.
3. The **Go Worker** receives the completion event via Redis Pub/Sub.
4. You instantly receive the structured result in your `wscat` terminal:

```json
{
  "job_id": "...",
  "status": "completed",
  "smiles_input": "CC(=O)Oc1ccccc1C(=O)O",
  "tox_score": 0.542,
  "tox_class": "Moderate",
  "llm_explanation": "The compound CC(=O)Oc1ccccc1C(=O)O shows moderate predicted toxicity..."
}
```

---

## 4. Troubleshooting
- **401 Unauthorized:** Your token is missing or expired. Re-login to get a fresh one.
- **Worker not picking up jobs:** Check the `python-worker` console for connection errors to Upstash Redis.
- **DB errors:** Ensure you ran the `supabase_migration.sql` script in your Supabase dashboard.
