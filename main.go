package main

import (
	"log"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"

	"hackathon-backend-go/config"
	"hackathon-backend-go/handlers"
	"hackathon-backend-go/worker"
)

func main() {
	_ = godotenv.Load()

	config.InitPostgres()
	config.InitRedis()

	go worker.ListenForCompletions()

	r := gin.Default()

	// ── Health endpoint ──────────────────────────────────────
	r.GET("/health", handlers.HealthCheck)

	// ── Authentication Endpoints ─────────────────────────────
	auth := r.Group("/auth")
	{
		auth.POST("/signup", handlers.Signup)
		auth.POST("/login", handlers.Login)
		auth.POST("/logout", handlers.Logout)
		auth.GET("/oauth/:provider", handlers.OAuthRedirect)
	}

	// ── V1 API (Protected Routes can use middleware.AuthMiddleware()) ──
	v1 := r.Group("/v1/api")
	// Example: v1.Use(middleware.AuthMiddleware())
	{
		// ── Supabase Todos Endpoint ──────────────────────────────
		v1.GET("/todos", handlers.GetTodos)

		// ── Job Ingestion Endpoint ───────────────────────────────
		v1.POST("/jobs", handlers.IngestJob)

		// ── Job WebSocket Endpoint ───────────────────────────────
		v1.GET("/jobs/ws/:job_id", handlers.JobWebSocket)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("🚀 Server starting on :%s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("❌ Server failed: %v", err)
	}
}
