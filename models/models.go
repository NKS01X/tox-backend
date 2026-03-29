package models

import (
	"time"

	"gorm.io/datatypes"
)

// Prediction represents a toxicity prediction job stored in Supabase.
// Maps to the `predictions` table created via supabase_migration.sql.
type Prediction struct {
	ID             string    `gorm:"type:uuid;primaryKey;default:gen_random_uuid()" json:"id"`
	Status         string    `gorm:"not null;default:'queued'"                       json:"status"`
	SmilesInput    string    `gorm:"column:smiles_input;not null"                    json:"smiles_input"`
	ToxScore       *float64  `gorm:"column:tox_score"                                json:"tox_score"`
	ToxClass       *string                `gorm:"column:tox_class"                                json:"tox_class"`
	LLMExplanation *string            `gorm:"column:llm_explanation"                          json:"llm_explanation"`
	ExtraData      datatypes.JSON     `gorm:"type:jsonb"                                      json:"extra_data"`
	CreatedAt      time.Time          `gorm:"column:created_at;autoCreateTime"                json:"created_at"`
}

func (Prediction) TableName() string { return "predictions" }

// User represents the users table for authentication (custom auth, not Supabase Auth).
type User struct {
	ID           uint   `gorm:"primaryKey"             json:"id"`
	Email        string `gorm:"uniqueIndex;not null"   json:"email"`
	PasswordHash string `gorm:"not null"               json:"-"`
}
