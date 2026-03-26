package worker

import (
	"context"
	"log"

	"github.com/gin-gonic/gin"
	"hackathon-backend-go/config"
	"hackathon-backend-go/models"
)

func ListenForCompletions() {
	ctx := context.Background()
	pubsub := config.RDB.Subscribe(ctx, "job_completed_events")
	defer pubsub.Close()

	ch := pubsub.Channel()
	for msg := range ch {
		jobID := msg.Payload

		var job models.JobResult
		if err := config.DB.Where("job_id = ?", jobID).First(&job).Error; err != nil {
			log.Printf("❌ Failed to find job result %s in DB: %v", jobID, err)
			continue
		}

		config.ClientsMu.Lock()
		conn, exists := config.Clients[jobID]
		if exists {
			delete(config.Clients, jobID)
		}
		config.ClientsMu.Unlock()

		if exists {
			_ = conn.WriteJSON(gin.H{
				"job_id": jobID,
				"status": "completed",
				"result": job.Result,
			})
			conn.Close()
		}
	}
}
