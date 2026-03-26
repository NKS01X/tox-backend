package handlers

import (
	"context"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"hackathon-backend-go/config"
	"hackathon-backend-go/models"
)

func IngestJob(c *gin.Context) {
	var req struct {
		Prompt string `json:"prompt" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request payload: " + err.Error()})
		return
	}

	jobID := uuid.New().String()

	ctx := context.Background()
	err := config.RDB.XAdd(ctx, &redis.XAddArgs{
		Stream: "llm_task_queue",
		Values: map[string]interface{}{
			"job_id": jobID,
			"prompt": req.Prompt,
		},
	}).Err()

	if err != nil {
		log.Printf("Failed to enqueue job %s: %v", jobID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to enqueue job"})
		return
	}

	c.JSON(http.StatusAccepted, gin.H{
		"job_id": jobID,
		"status": "queued",
	})
}

func JobWebSocket(c *gin.Context) {
	jobID := c.Param("job_id")

	var existing models.JobResult
	if err := config.DB.Where("job_id = ?", jobID).First(&existing).Error; err == nil {
		conn, err := config.Upgrader.Upgrade(c.Writer, c.Request, nil)
		if err == nil {
			_ = conn.WriteJSON(gin.H{"job_id": jobID, "status": "completed", "result": existing.Result})
			conn.Close()
		}
		return
	}

	conn, err := config.Upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Println("❌ Failed to upgrade websocket:", err)
		return
	}

	config.ClientsMu.Lock()
	config.Clients[jobID] = conn
	config.ClientsMu.Unlock()

	go func() {
		defer func() {
			config.ClientsMu.Lock()
			delete(config.Clients, jobID)
			config.ClientsMu.Unlock()
			conn.Close()
		}()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				break
			}
		}
	}()
}
