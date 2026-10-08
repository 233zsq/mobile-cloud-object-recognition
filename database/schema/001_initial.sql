-- Initial schema 001; generated from backend/app/models/__init__.py.

-- MySQL 8.0.16+; run inside the selected empty application database.

-- Future structure changes require a new versioned migration.

SET NAMES utf8mb4;

SET time_zone = '+00:00';

CREATE TABLE category (
	category_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	id INTEGER NOT NULL,
	label_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	display_name VARCHAR(64) NOT NULL,
	definition VARCHAR(512),
	PRIMARY KEY (category_version, id),
	CONSTRAINT uq_category_label UNIQUE (category_version, label_key),
	CONSTRAINT ck_category_id CHECK (id >= 0 AND id <= 9)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE model_version (
	version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	category_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	model_sha256 VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	labels_sha256 VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	release_status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	low_confidence_threshold DOUBLE NOT NULL,
	registered_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
	PRIMARY KEY (version),
	CONSTRAINT uq_model_category_version UNIQUE (version, category_version),
	CONSTRAINT ck_model_status CHECK (release_status IN ('experimental', 'frozen')),
	CONSTRAINT ck_model_threshold CHECK (low_confidence_threshold >= 0 AND low_confidence_threshold <= 1)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE inference_record (
	record_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	client_id VARCHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	inference_source VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	model_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	category_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	predicted_id INTEGER NOT NULL,
	confidence DOUBLE NOT NULL,
	latency_ms BIGINT NOT NULL,
	captured_at DATETIME(3) NOT NULL,
	payload_sha256 VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	corrected_id INTEGER,
	corrected_at DATETIME(3),
	revision BIGINT NOT NULL DEFAULT 0,
	created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
	PRIMARY KEY (record_id),
	CONSTRAINT fk_record_model FOREIGN KEY(model_version, category_version) REFERENCES model_version (version, category_version),
	CONSTRAINT fk_record_prediction FOREIGN KEY(category_version, predicted_id) REFERENCES category (category_version, id),
	CONSTRAINT fk_record_correction FOREIGN KEY(category_version, corrected_id) REFERENCES category (category_version, id),
	CONSTRAINT ck_record_source CHECK (inference_source IN ('device', 'cloud')),
	CONSTRAINT ck_record_confidence CHECK (confidence >= 0 AND confidence <= 1),
	CONSTRAINT ck_record_latency CHECK (latency_ms >= 0),
	CONSTRAINT ck_record_revision CHECK (revision >= 0),
	CONSTRAINT ck_record_correction_state CHECK ((corrected_id IS NULL AND corrected_at IS NULL AND revision = 0) OR (corrected_id IS NOT NULL AND corrected_at IS NOT NULL AND revision > 0))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_record_captured ON inference_record (captured_at);

CREATE INDEX ix_record_model_captured ON inference_record (model_version, captured_at);

CREATE TABLE sample (
	sample_id VARCHAR(128) NOT NULL,
	image_path VARCHAR(512) NOT NULL,
	image_sha256 VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	category_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
	category_id INTEGER NOT NULL,
	object_id VARCHAR(128),
	session_id VARCHAR(128),
	collector VARCHAR(128),
	captured_at DATETIME(3),
	split_name VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin,
	review_status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'pending',
	data_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
	PRIMARY KEY (sample_id),
	CONSTRAINT fk_sample_category FOREIGN KEY(category_version, category_id) REFERENCES category (category_version, id),
	CONSTRAINT ck_sample_split CHECK (split_name IS NULL OR split_name IN ('train', 'validation', 'test')),
	CONSTRAINT ck_sample_review CHECK (review_status IN ('pending', 'approved', 'rejected'))
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX ix_sample_image_sha256 ON sample (image_sha256);
