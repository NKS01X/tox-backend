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
		Smiles string `json:"smiles" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request payload: " + err.Error()})
		return
	}

	// ── Cache check ─────────────────────────────────────────────────────────
	// If this SMILES has already been processed successfully, return the
	// cached result immediately without re-running the model.
	var cached models.Prediction
	if err := config.DB.
		Where("smiles_input = ? AND status = ?", req.Smiles, "completed").
		Order("created_at DESC").
		First(&cached).Error; err == nil {
		log.Printf("✅ Cache hit for SMILES %.30s — returning existing result", req.Smiles)
		c.JSON(http.StatusOK, buildWSPayload(&cached))
		return
	}

	jobID := uuid.New().String()

	// Persist the job row immediately so status is queryable from the start
	prediction := models.Prediction{
		ID:          jobID,
		Status:      "queued",
		SmilesInput: req.Smiles,
	}
	if err := config.DB.Create(&prediction).Error; err != nil {
		log.Printf("Failed to create prediction row for job %s: %v", jobID, err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create job record"})
		return
	}

	// Enqueue the smile in the Redis stream for the Python LLM worker
	ctx := context.Background()
	err := config.RDB.XAdd(ctx, &redis.XAddArgs{
		Stream: "llm_task_queue",
		Values: map[string]interface{}{
			"job_id": jobID,
			"smiles": req.Smiles,
		},
	}).Err()
	if err != nil {
		log.Printf("Failed to enqueue job %s: %v", jobID, err)
		// Mark the DB row as failed since we couldn't queue it
		config.DB.Model(&models.Prediction{}).Where("id = ?", jobID).Update("status", "failed")
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

	// Fast-path: job already completed before the WebSocket was established
	// (e.g. the LLM worker finished before the client reconnected)
	var existing models.Prediction
	if err := config.DB.Where("id = ?", jobID).First(&existing).Error; err == nil && existing.Status == "completed" {
		conn, err := config.Upgrader.Upgrade(c.Writer, c.Request, nil)
		if err == nil {
			_ = conn.WriteJSON(buildWSPayload(&existing))
			conn.Close()
		}
		return
	}

	conn, err := config.Upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		log.Println("❌ Failed to upgrade websocket:", err)
		return
	}

	// Register this connection so the worker listener can push to it
	config.ClientsMu.Lock()
	config.Clients[jobID] = conn
	config.ClientsMu.Unlock()

	// Keep the connection alive; detect client disconnects via read errors
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

// buildWSPayload constructs the structured JSON payload the frontend expects.
func buildWSPayload(p *models.Prediction) gin.H {
	return gin.H{
		"job_id":          p.ID,
		"status":          p.Status,
		"smiles_input":    p.SmilesInput,
		"tox_score":       p.ToxScore,
		"tox_class":       p.ToxClass,
		"llm_explanation": p.LLMExplanation,
	}
}
