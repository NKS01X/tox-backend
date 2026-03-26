package models

// JobResult represents a finished job stored in DB
type JobResult struct {
	JobID  string `gorm:"primaryKey"`
	Result string
}

// Todo represents the 'todos' table in Supabase
type Todo struct {
	ID   int64  `gorm:"primaryKey" json:"id"`
	Name string `json:"name"`
}

// User represents the users table for authentication
type User struct {
	ID           uint   `gorm:"primaryKey" json:"id"`
	Email        string `gorm:"uniqueIndex;not null" json:"email"`
	PasswordHash string `gorm:"not null" json:"-"`
}
