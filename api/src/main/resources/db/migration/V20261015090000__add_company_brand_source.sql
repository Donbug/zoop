-- Keep logo and color provenance separate from the public company profile.
ALTER TABLE companies ADD COLUMN brand_source text;
