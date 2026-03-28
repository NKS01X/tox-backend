package tests

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSignupAndLogin(t *testing.T) {
	r, _, cleanup := setupTestEnv()
	defer cleanup()

	// 1. Valid Signup
	payload := []byte(`{"email":"test@example.com","password":"password123"}`)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/auth/signup", bytes.NewBuffer(payload))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusCreated, w.Code)

	// 2. Duplicate Signup (Conflict)
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", "/auth/signup", bytes.NewBuffer(payload))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)

	assert.Equal(t, http.StatusConflict, w2.Code)

	// 3. Valid Login
	w3 := httptest.NewRecorder()
	req3, _ := http.NewRequest("POST", "/auth/login", bytes.NewBuffer(payload))
	req3.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w3, req3)

	assert.Equal(t, http.StatusOK, w3.Code)

	var response map[string]interface{}
	err := json.Unmarshal(w3.Body.Bytes(), &response)
	assert.NoError(t, err)
	assert.Contains(t, response, "token")
	assert.NotEmpty(t, response["token"])

	// 4. Invalid Login (Wrong password)
	invalidPayload := []byte(`{"email":"test@example.com","password":"wrongpassword"}`)
	w4 := httptest.NewRecorder()
	req4, _ := http.NewRequest("POST", "/auth/login", bytes.NewBuffer(invalidPayload))
	req4.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w4, req4)

	assert.Equal(t, http.StatusUnauthorized, w4.Code)
}
