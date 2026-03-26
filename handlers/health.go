package handlers

import (
	"context"
	"net/http"

	"github.com/gin-gonic/gin"
	"hackathon-backend-go/config"
)

func HealthCheck(c *gin.Context) {
	// Postgres
	sqlDB, err := config.DB.DB()
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status":   "unhealthy",
			"postgres": err.Error(),
		})
		return
	}
	if err := sqlDB.Ping(); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status":   "unhealthy",
			"postgres": err.Error(),
		})
		return
	}

	// Redis
	ctx := context.Background()
	if err := config.RDB.Ping(ctx).Err(); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"status": "unhealthy",
			"redis":  err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"status":   "healthy",
		"postgres": "ok",
		"redis":    "ok",
	})
}
