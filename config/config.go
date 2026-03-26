package config

import (
	"context"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"hackathon-backend-go/models"
)

var (
	DB  *gorm.DB
	RDB *redis.Client

	Upgrader = websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
	Clients   = make(map[string]*websocket.Conn)
	ClientsMu sync.Mutex
)

// InitPostgres connects to PostgreSQL using GORM

// gorm se ham direct connect ho jate hai redis se no need of
// long polling or websocket connection
func InitPostgres() {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = "host=localhost user=appuser password=apppassword dbname=hackathon port=5432 sslmode=disable"
	}

	var err error
	for i := 0; i < 10; i++ {
		DB, err = gorm.Open(postgres.Open(dsn), &gorm.Config{})
		if err == nil {
			log.Println("✅ Connected to PostgreSQL (Supabase)")
			DB.AutoMigrate(&models.JobResult{}, &models.Todo{}, &models.User{})
			return
		}
		log.Printf("⏳ Waiting for PostgreSQL (%d/10)...", i+1)
		time.Sleep(2 * time.Second)
	}
	log.Fatalf("❌ Could not connect to PostgreSQL: %v", err)
}

// InitRedis connects to Redis.
func InitRedis() {
	upstashURL := os.Getenv("UPSTASH_REDIS_URL")
	if upstashURL != "" {
		opt, err := redis.ParseURL(upstashURL)
		if err != nil {
			log.Fatalf("❌ Failed to parse UPSTASH_REDIS_URL: %v", err)
		}
		RDB = redis.NewClient(opt)
	} else {
		addr := os.Getenv("REDIS_ADDR")
		if addr == "" {
			addr = "localhost:6379"
		}
		RDB = redis.NewClient(&redis.Options{Addr: addr})
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := RDB.Ping(ctx).Err(); err != nil {
		log.Fatalf("❌ Could not connect to Redis: %v", err)
	}
	log.Println("✅ Connected to Redis")
}
