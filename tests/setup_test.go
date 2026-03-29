package tests

import (
	"log"
	"os"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/redis/go-redis/v9"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"hackathon-backend-go/config"
	"hackathon-backend-go/handlers"
	"hackathon-backend-go/middleware"
)

func setupTestEnv() (*gin.Engine, *miniredis.Miniredis, func()) {
	// 1. Setup Miniredis
	mr, err := miniredis.Run()
	if err != nil {
		log.Fatalf("miniredis setup failed: %v", err)
	}

	config.RDB = redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})

	// 2. Setup SQLite in-memory DB
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	if err != nil {
		log.Fatalf("sqlite setup failed: %v", err)
	}
	config.DB = db

	// Manually create tables to bypass Postgres-specific UUID default expressions
	err = db.Exec(`
		CREATE TABLE users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			email TEXT UNIQUE NOT NULL,
			password_hash TEXT NOT NULL
		);
	`).Error
	if err != nil {
		log.Fatalf("failed to create users table: %v", err)
	}

	err = db.Exec(`
		CREATE TABLE predictions (
			id TEXT PRIMARY KEY,
			status TEXT DEFAULT 'queued',
			smiles_input TEXT NOT NULL,
			tox_score REAL,
			tox_class TEXT,
			llm_explanation TEXT,
			extra_data JSON,
			created_at DATETIME DEFAULT CURRENT_TIMESTAMP
		);
	`).Error
	if err != nil {
		log.Fatalf("failed to create predictions table: %v", err)
	}

	// 3. Setup Gin Router
	gin.SetMode(gin.TestMode)
	r := gin.New()

	r.GET("/health", handlers.HealthCheck)

	auth := r.Group("/auth")
	{
		auth.POST("/signup", handlers.Signup)
		auth.POST("/login", handlers.Login)
		auth.POST("/logout", handlers.Logout)
	}

	v1 := r.Group("/v1/api")
	// Set JWT secret for tests
	os.Setenv("JWT_SECRET", "test-secret")
	v1.Use(middleware.AuthMiddleware())
	{
		v1.POST("/jobs", handlers.IngestJob)
		v1.GET("/jobs/ws/:job_id", handlers.JobWebSocket)
	}

	// Cleanup function
	cleanup := func() {
		mr.Close()
		sqlDB, _ := db.DB()
		if sqlDB != nil {
			sqlDB.Close()
		}
	}

	return r, mr, cleanup
}

func generateTestJWT(userID uint) string {
	os.Setenv("JWT_SECRET", "test-secret")
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"user_id": userID,
		"exp":     time.Now().Add(time.Hour * 1).Unix(),
	})
	signed, _ := token.SignedString([]byte("test-secret"))
	return signed
}
