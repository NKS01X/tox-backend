package worker

import (
	"context"
	"log"

	"hackathon-backend-go/config"
	"hackathon-backend-go/models"

	"github.com/gin-gonic/gin"
)

// ListenForCompletions subscribes to the Redis Pub/Sub channel that the
// Python LLM worker publishes to once inference is done.
// It fetches the completed Prediction from PostgreSQL and pushes the
// structured result to the waiting WebSocket client (if still connected).
func ListenForCompletions() {
	ctx := context.Background()
	pubsub := config.RDB.Subscribe(ctx, "job_completed_events")
	defer pubsub.Close()

	log.Println("👂 Worker: listening for job completions on 'job_completed_events'")

	ch := pubsub.Channel()
	for msg := range ch {
		jobID := msg.Payload

		var prediction models.Prediction
		if err := config.DB.Where("id = ?", jobID).First(&prediction).Error; err != nil {
			log.Printf("❌ Worker: failed to find prediction %s in DB: %v", jobID, err)
			continue
		}

		config.ClientsMu.Lock()
		conn, exists := config.Clients[jobID]
		if exists {
			delete(config.Clients, jobID)
		}
		config.ClientsMu.Unlock()

		if exists {
			payload := gin.H{
				"job_id":          prediction.ID,
				"status":          prediction.Status,
				"smiles_input":    prediction.SmilesInput,
				"tox_score":       prediction.ToxScore,
				"tox_class":       prediction.ToxClass,
				"llm_explanation": prediction.LLMExplanation,
			}
			_ = conn.WriteJSON(payload)
			conn.Close()
			log.Printf("✅ Worker: pushed result for job %s to WebSocket client", jobID)
		} else {
			log.Println(msg.Payload)
			log.Printf("ℹ️  Worker: job %s completed but no active WS client found (client may have disconnected)", jobID)
		}
	}
}
