package middleware

import (
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// AuthMiddleware validates a JWT in the Authorization header.
//
// It checks the following secrets in order:
//  1. SUPABASE_JWT_SECRET — for tokens issued by Supabase Auth (frontend login via Supabase SDK)
//  2. JWT_SECRET          — for tokens issued by this backend's own /auth/login endpoint
//
// Both use HS256 signing, so the same parsing logic applies.
func AuthMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		var rawToken string

		authHeader := c.GetHeader("Authorization")
		if authHeader != "" {
			parts := strings.Split(authHeader, " ")
			if len(parts) != 2 || parts[0] != "Bearer" {
				c.JSON(http.StatusUnauthorized, gin.H{"error": "Authorization header must be formatted as: Bearer <token>"})
				c.Abort()
				return
			}
			rawToken = parts[1]
		} else {
			// Fallback to query parameter (often needed for WebSockets)
			rawToken = c.Query("token")
		}

		if rawToken == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Authorization header or ?token query parameter is required"})
			c.Abort()
			return
		}

		// Collect candidate secrets (non-empty only)
		var secrets []string
		if s := os.Getenv("SUPABASE_JWT_SECRET"); s != "" {
			secrets = append(secrets, s)
		}
		if s := os.Getenv("JWT_SECRET"); s != "" {
			secrets = append(secrets, s)
		}
		if len(secrets) == 0 {
			secrets = []string{"super-secret-hackathon-key-123"}
		}

		// Try each secret until one validates
		var (
			validToken *jwt.Token
			parseErr   error
		)
		for _, secret := range secrets {
			sec := secret // capture for closure
			validToken, parseErr = jwt.Parse(rawToken, func(token *jwt.Token) (interface{}, error) {
				if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
					return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
				}
				return []byte(sec), nil
			})
			if parseErr == nil && validToken.Valid {
				break
			}
		}

		if parseErr != nil || !validToken.Valid {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "Invalid or expired token"})
			c.Abort()
			return
		}

		if claims, ok := validToken.Claims.(jwt.MapClaims); ok {
			// Supabase tokens use "sub" for user UUID; our tokens use "user_id"
			if sub, ok := claims["sub"]; ok {
				c.Set("user_id", sub)
			} else {
				c.Set("user_id", claims["user_id"])
			}
		}

		c.Next()
	}
}
