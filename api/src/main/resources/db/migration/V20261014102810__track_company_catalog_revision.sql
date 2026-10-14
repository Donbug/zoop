-- Internal pagination metadata, independent of the GraphDB version.
CREATE TABLE company_catalog_revision (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    revision bigint NOT NULL CHECK (revision > 0)
);

INSERT INTO company_catalog_revision (singleton, revision) VALUES (true, 1);

CREATE FUNCTION zoop_advance_company_catalog_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Transactional row updates serialize writers and roll back with catalog changes.
    UPDATE company_catalog_revision SET revision = revision + 1 WHERE singleton = true;
    RETURN NULL;
END;
$$;

CREATE TRIGGER companies_catalog_revision
AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON companies
FOR EACH STATEMENT EXECUTE FUNCTION zoop_advance_company_catalog_revision();
