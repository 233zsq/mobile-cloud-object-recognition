-- Migration 002: immutable scope evidence; preserves all existing records.

-- Apply once in the existing application database before activating the new backend.

SET NAMES utf8mb4;

SET time_zone = '+00:00';

CREATE TABLE inference_decision (
	record_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	policy_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
	policy_sha256 VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
	knownness DOUBLE,
	manual_confirmed BOOL NOT NULL DEFAULT 0,
	PRIMARY KEY (record_id),
	CONSTRAINT fk_decision_record FOREIGN KEY(record_id) REFERENCES inference_record (record_id),
	CONSTRAINT ck_decision_status CHECK (status IN ('accepted', 'uncertain', 'unavailable')),
	CONSTRAINT ck_decision_knownness CHECK (knownness IS NULL OR (knownness >= 0 AND knownness <= 1)),
	CONSTRAINT ck_decision_confirmed CHECK (status = 'accepted' OR manual_confirmed = 1)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_decision_status ON inference_decision (status, record_id);
