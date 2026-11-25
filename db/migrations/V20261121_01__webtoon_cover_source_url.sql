-- Record the provider's cover URL separately from the image displayed by the app.
-- A URL is source metadata only; it does not grant rights to fetch, cache, or display the image.
ALTER TABLE webtoon_metadata
    ADD COLUMN cover_source_url VARCHAR(2048) NULL AFTER official_url;
