-- Additive follow-up for databases that already applied the original webtoon
-- migration. No rows are deleted or rewritten. Apply only after the database
-- owner approves this schema change and a verified backup is available.
-- source_provider is provenance; an external-ID mapping is optional.
ALTER TABLE webtoon_metadata
    DROP FOREIGN KEY fk_webtoon_metadata_source_identity;
