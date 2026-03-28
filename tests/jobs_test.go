package tests

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"

	"hackathon-backend-go/config"
	"hackathon-backend-go/models"
)

func TestIngestJobCacheMissAndHit(t *testing.T) {
	r, _, cleanup := setupTestEnv()
	defer cleanup()

	token := generateTestJWT(1)

	// 1. Initial Job Ingestion (Cache Miss)
	payload := []byte(`{"smiles":"CCO"}`)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/v1/api/jobs", bytes.NewBuffer(payload))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusAccepted, w.Code) // 202 expected for cache miss

	var response map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &response)
	assert.NoError(t, err)
	assert.Equal(t, "queued", response["status"])
	assert.NotEmpty(t, response["job_id"])
	jobID := response["job_id"].(string)

	// 2. Simulate worker completing the job
	toxScore := 0.25
	toxClass := "Low"
	llmExplanation := "Test explanation"
	config.DB.Model(&models.Prediction{}).Where("id = ?", jobID).Updates(map[string]interface{}{
		"status":          "completed",
		"tox_score":       toxScore,
		"tox_class":       toxClass,
		"llm_explanation": llmExplanation,
	})

	// 3. Second Job Ingestion with SAME SMILES (Cache Hit)
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", "/v1/api/jobs", bytes.NewBuffer(payload))
	req2.Header.Set("Content-Type", "application/json")
	req2.Header.Set("Authorization", "Bearer "+token)
	r.ServeHTTP(w2, req2)

	assert.Equal(t, http.StatusOK, w2.Code) // 200 expected for cache hit

	var cacheResponse map[string]interface{}
	err = json.Unmarshal(w2.Body.Bytes(), &cacheResponse)
	assert.NoError(t, err)
	assert.Equal(t, "completed", cacheResponse["status"])
	assert.Equal(t, float64(0.25), cacheResponse["tox_score"])
	assert.Equal(t, "Low", cacheResponse["tox_class"])
	assert.Equal(t, "Test explanation", cacheResponse["llm_explanation"])
	assert.Equal(t, "CCO", cacheResponse["smiles_input"])
}
