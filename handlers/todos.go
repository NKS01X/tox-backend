package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"hackathon-backend-go/config"
	"hackathon-backend-go/models"
)

func GetTodos(c *gin.Context) {
	var todos []models.Todo
	if err := config.DB.Find(&todos).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to fetch todos: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, todos)
}
