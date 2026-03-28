# 🧪 Tox-Detector Testing Guide

This guide walks through the full flow: user registration → login → submitting a chemical SMILES string → receiving a real-time toxicity prediction, plus validating the **SMILES result cache**.

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
```bash
curl -X POST http://localhost:8080/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email": "tox_tester@example.com", "password": "password123"}'
```

### B. Login — get your JWT token
```bash
curl -X POST http://localhost:8080/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "tox_tester@example.com", "password": "password123"}'
```
*Copy the `"token"` value from the response and export it:*
```bash
export TOKEN="<paste token here>"
```

---

## 3. Toxicity Prediction Flow

### A. Submit a new SMILES job (cache miss)
```bash
curl -X POST http://localhost:8080/v1/api/jobs \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O"}'
```
**Expected → `202 Accepted`:**
```json
{ "job_id": "...", "status": "queued" }
```

### B. Wait for the real-time result via WebSocket
```bash
# Replace <JOB_ID> with the id from Step A
wscat -c ws://localhost:8080/v1/api/jobs/ws/<JOB_ID> -H "Authorization: Bearer $TOKEN"
```

**What happens:**
1. Request lands in the Redis Stream (`llm_task_queue`).
2. Python worker detects it, runs the ML toxicity model, and updates Supabase.
3. Go worker receives the completion event via Redis Pub/Sub.
4. WebSocket frame is pushed:

```json
{
  "job_id": "...",
  "status": "completed",
  "smiles_input": "CC(=O)Oc1ccccc1C(=O)O",
  "tox_score": 0.1523,
  "tox_class": "Non-toxic",
  "llm_explanation": "The compound CC(=O)Oc1ccccc1C(=O)O shows very low predicted toxicity (score 0.1523)."
}
```

---

## 4. SMILES Cache Testing

The backend short-circuits inference for previously-processed SMILES. No WebSocket needed — the result is returned synchronously in the HTTP response.

### A. Submit the *same* SMILES again (cache hit)
```bash
curl -X POST http://localhost:8080/v1/api/jobs \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"smiles": "CC(=O)Oc1ccccc1C(=O)O"}'
```
**Expected → `200 OK`** (instant, no WebSocket needed):
```json
{
  "job_id": "<original_job_id>",
  "status": "completed",
  "smiles_input": "CC(=O)Oc1ccccc1C(=O)O",
  "tox_score": 0.1523,
  "tox_class": "Non-toxic",
  "llm_explanation": "..."
}
```
> The Python worker log should show **no new job received** — inference was skipped entirely.

### B. Submit a different SMILES (cache miss, new job)
```bash
curl -X POST http://localhost:8080/v1/api/jobs \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"smiles": "c1ccccc1"}'
```
**Expected → `202 Accepted`** (new job queued, Python worker picks it up).

---

## 5. Response Code Reference

| HTTP Status | Meaning |
|---|---|
| `200 OK` | Cache hit — full result returned immediately in the response body |
| `202 Accepted` | Cache miss — job queued; connect via WebSocket to get the result |
| `400 Bad Request` | Missing or invalid `smiles` field |
| `401 Unauthorized` | JWT missing or expired |
| `500 Internal Server Error` | Redis or DB failure |

---

## 6. Troubleshooting
- **401 Unauthorized:** Token is missing or expired. Re-login to get a fresh one.
- **Worker not picking up jobs:** Check the `python-worker` console for Upstash Redis connection errors.
- **DB errors:** Ensure you ran `supabase_migration.sql` in your Supabase dashboard.
- **Cache not triggering:** The first job must have `status = 'completed'` in the DB. Check if the Python worker finished processing before retrying.
