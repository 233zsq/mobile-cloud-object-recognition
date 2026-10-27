-- Migration 003: allow a human reviewer to mark a record as outside the ten model classes.
-- Apply once after 001 and 002, before activating clients that submit corrected_label.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

ALTER TABLE inference_record
    ADD COLUMN corrected_label VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER corrected_id;

ALTER TABLE inference_record
    DROP CHECK ck_record_correction_state;

ALTER TABLE inference_record
    ADD CONSTRAINT ck_record_correction_label
        CHECK (corrected_label IS NULL OR corrected_label = 'other'),
    ADD CONSTRAINT ck_record_correction_state
        CHECK (
            (corrected_id IS NULL AND corrected_label IS NULL AND corrected_at IS NULL AND revision = 0)
            OR
            (corrected_at IS NOT NULL AND revision > 0 AND (
                (corrected_id IS NOT NULL AND corrected_label IS NULL)
                OR (corrected_id IS NULL AND corrected_label = 'other')
            ))
        );
