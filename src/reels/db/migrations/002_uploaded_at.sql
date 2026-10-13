-- Track upload time separately from created_at (used for gallery ordering).

ALTER TABLE videos ADD COLUMN uploaded_at TEXT;

UPDATE videos SET uploaded_at = created_at WHERE uploaded_at IS NULL;
