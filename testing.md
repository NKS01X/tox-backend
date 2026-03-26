# Local Testing Guide

This guide walks you through the process of manually testing the full event-driven flow of the Go backend—from ingesting a job, to mocking the worker, and receiving the final result over a WebSocket.

## Prerequisites
1. Ensure your `.env` is configured properly.
2. Start the backend:
```bash
# If using the included docker-compose.yml
docker-compose up --build

# If running natively with Upstash and local Postgres DB
go build .
./hackathon-backend-go
```

---

## Step 1: Ingest a Job
Send a POST request to the API to simulate a client submitting a task. You can use **cURL**, **Postman**, or **Insomnia**.

```bash
curl -X POST http://localhost:8080/v1/api/jobs \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Tell me a joke"}'
```

**Expected Response (HTTP 202 Accepted):**
```json
{
  "job_id": "b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```
*Copy the `job_id` returned for the next step.*

---

## Step 2: Connect to the WebSocket
To simulate the client waiting for the real-time result, connect to the WebSocket endpoint using the `job_id` from Step 1.

You can use a tool like [wscat](https://github.com/websockets/wscat) or Postman's WebSocket client:
```bash
# Install wscat if you don't have it
npm install -g wscat

# Connect
wscat -c ws://localhost:8080/v1/api/jobs/ws/b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx
```
*The connection will remain connected, open, and idle.*

---

## Step 3: Mock the AI Worker
In a real environment, an external Python (or node) worker reads the Redis Stream (`llm_task_queue`), does the heavy lifting, and completes the transaction. Here, we'll manually simulate the worker's two final completion steps.

### A. Save the Result to PostgreSQL
Connect to your local Postgres instance. If you used `docker-compose`:
```bash
docker exec -it hackathon-backend-go-postgres-1 psql -U appuser -d hackathon
```

Insert the mock generated result for the exact `job_id`:
```sql
INSERT INTO job_results (job_id, result) 
VALUES ('b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx', 'Here is the mocked AI response!');
```

### B. Fire the Redis Pub/Sub Event
Now, trigger the Pub/Sub event to notify the Go backend that the job is officially complete. 

If using the **Upstash Redis** URL you provided earlier, you can use the **Upstash Web CLI** in your browser console, or use `redis-cli` with the TLS URL:
```bash
redis-cli -u "rediss://default:YOUR_PASSWORD@your-endpoint.upstash.io:6379" PUBLISH job_completed_events "b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx"
```

If you are just using **local Docker Redis**:
```bash
docker exec -it hackathon-backend-go-redis-1 redis-cli
> PUBLISH job_completed_events "b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx"
```

---

## Step 4: Verification 🚀
Go back to your `wscat` terminal from Step 2. The exact moment you run the `PUBLISH` command, you should instantly see the Go WebSocket push the JSON result downstream and automatically shut the connection:

```json
{
  "job_id": "b11a5862-2f3b-419b-xxxx-xxxxxxxxxxxx",
  "result": "Here is the mocked AI response!",
  "status": "completed"
}
```
*Disconnected (code 1000).* ✨

---

## Testing Authentication

You can manually verify that the bcrypt hashing and JWT issuance is working correctly by using **cURL** or Postman.

### A. Signup a New User
Send a `POST` request to register a new user:
```bash
curl -X POST http://localhost:8080/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com", "password": "supersecurepassword"}'
```
**Expected Response (HTTP 201 Created):**
```json
{
  "message": "User registered successfully",
  "user_id": 1
}
```

### B. Login and Receive JWT
Send a `POST` request with the same credentials to retrieve your signed JSON Web Token (JWT):
```bash
curl -X POST http://localhost:8080/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com", "password": "supersecurepassword"}'
```
**Expected Response (HTTP 200 OK):**
```json
{
  "message": "Login successful",
  "token": "eyJhbGciOiJIUzI1NiIsInR5c..."
}
```
*You can now pass this `token` into the `Authorization: Bearer <token>` header of any protected route!*
