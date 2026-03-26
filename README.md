# Event-Driven LLM Backend (Go)

A high-performance, event-driven backend service built with Go (Gin), PostgreSQL, and Redis (or Upstash Redis) designed to handle asynchronous tasks like LLM inference generations.

## 🏗️ Architecture Flow
1. **Ingestion**: The client sends a REST request to ingest a job. The server yields a UUID instantly and delegates the logic to a queue.
2. **Queuing**: The request payload and the `job_id` are pushed onto a **Redis Stream** (`llm_task_queue`). (*Note: An external worker is expected to process this queue and save results in Postgres*).
3. **Real-time Delivery**: The client connects to a **WebSocket** associated with their `job_id`.
4. **Completion**: A worker pushes an event payload (the `job_id`) to the **Redis Pub/Sub** channel (`job_completed_events`). The Go WebSocket subscriber intercepts it, fetches the final `Result` from Postgres, pipes it down to the client, and safely closes the WS connection.

---

## 📁 Folder Structure
The Go monolithic backend has been structured into idiomatic, scalable internal packages:
* **`models/`**: GORM database entities (`User`, `JobResult`, `Todo`)
* **`config/`**: State management, Postgres, and Redis connection initializations
* **`middleware/`**: JWT validation and authorization guards
* **`handlers/`**: Dedicated API route logic (`/auth`, `/jobs`, `/todos`, `/health`)
* **`worker/`**: Background processes like the Redis Pub/Sub subscriber
* **`main.go`**: App entry point serving Gin routes

---

## 🚀 Setup & Requirements

### 1. Environment Variables (`.env`)
Create a `.env` file. If using Upstash, `UPSTASH_REDIS_URL` will take precedence over local connections.

```env
# Upstash Redis Connection (TLS enabled via rediss://)
UPSTASH_REDIS_URL=rediss://default:YOUR_PASSWORD@your-endpoint.upstash.io:6379

# PostgreSQL Connection
DATABASE_URL=host=localhost user=appuser password=apppassword dbname=hackathon port=5432 sslmode=disable
```

### 2. Running Locally

Since the backend is fully integrated with **Supabase PostgreSQL** and **Upstash Redis** in the cloud, you do **not** need Docker to run the application locally!

Simply run natively via Go:
```bash
go mod tidy
go run main.go
```
The server will boot on `http://localhost:8080`.

*(Note: The `docker-compose.yml` and `Dockerfile` are strictly kept for production cloud deployments or if you optionally wish to host local offline variants of Postgres/Redis instead of the cloud versions).*

---

## 🔌 API Endpoints

### 1. Health Check
Verifies connectivity for both PostgreSQL and Redis instances.
* **Endpoint**: `GET /health`
* **Response (`200 OK`):**
```json
{
  "postgres": "ok",
  "redis": "ok",
  "status": "healthy"
}
```

### 2. Fetch Supabase Todos
Fetches records from the `todos` table natively from your Supabase PostgreSQL instance using Go GORM.
* **Endpoint:** `GET /v1/api/todos`
* **Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "name": "Build the Go Backend"
  }
]
```

### 3. Ingest Job
Submits a task (prompt) to the Redis Stream.
* **Endpoint:** `POST /v1/api/jobs`
* **Headers:** `Content-Type: application/json`
* **JSON Received (Body):**
```json
{
  "prompt": "Write a short poem about coding."
}
```
* **JSON Sent (Response - `202 Accepted`):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued"
}
```

### 4. Real-Time Result (WebSocket)
Upgrades the connection to a persistent WebSocket. The stream stays open in an idle state (saving HTTP overhead polling) until the backend receives the Redis Pub/Sub trigger confirming the job is finished.
* **Endpoint:** `GET /v1/api/jobs/ws/:job_id`
* **Connection Type:** WebSocket (`ws://localhost:8080/v1/api/jobs/ws/...`)
* **JSON Sent (WebSocket Frame):**
Once the background worker completes the job and fires the Pub/Sub event, the backend queries Postgres and pushes this frame to the WebSocket before closing the connection gracefully:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": "Here is the final generated poem..."
}
```
*(Note: If the client connects to the WebSocket **after** the job is already marked completed in the database, the server will immediately push this same JSON frame and close the connection seamlessly).*

### 5. Authentication
Native secure authentication powered by bcrypt and stateless JSON Web Tokens (JWT).
* **`POST /auth/signup`**: Registers a user (requires `email` and `password`).
* **`POST /auth/login`**: Verifies credentials and issues a signed JWT (`token`).
* **`POST /auth/logout`**: Standardized logout termination instruction.
* **`GET /auth/oauth/:provider`**: Automatically redirects the client to Supabase's OAuth proxy logic. Note: The frontend will receive the callback, but Supabase’s HS256 tokens are natively ingestible by this Go backend's `AuthMiddleware` perfectly.
