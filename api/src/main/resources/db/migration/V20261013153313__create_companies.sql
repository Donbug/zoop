CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE FUNCTION zoop_normalize_company_text(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
RETURNS NULL ON NULL INPUT
AS $$
    -- Unicode White_Space characters, after NFKC. Internal whitespace is preserved.
    SELECT lower(btrim(normalize(value, NFKC),
        U&'\0009\000A\000B\000C\000D\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'))
$$;

CREATE TABLE companies (
    id text PRIMARY KEY,
    ticker text,
    exchange_code text,
    name text NOT NULL,
    name_key text NOT NULL,
    market text,
    aliases text[] NOT NULL DEFAULT '{}',
    search_text text NOT NULL,
    brand_color text,
    logo_url text,
    profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_companies_aliases_no_null CHECK (array_position(aliases, NULL) IS NULL)
);

CREATE UNIQUE INDEX uq_companies_exchange_ticker
    ON companies (exchange_code, ticker)
    WHERE exchange_code IS NOT NULL AND ticker IS NOT NULL;

CREATE INDEX ix_companies_ticker ON companies (ticker);
CREATE INDEX ix_companies_ticker_key ON companies (zoop_normalize_company_text(ticker));
CREATE INDEX ix_companies_name_key ON companies (name_key);
CREATE INDEX ix_companies_search_text_trgm ON companies USING gin (search_text gin_trgm_ops);

CREATE FUNCTION zoop_companies_update_search_columns()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    normalized_aliases text[];
BEGIN
    NEW.name_key := zoop_normalize_company_text(NEW.name);
    SELECT COALESCE(array_agg(zoop_normalize_company_text(alias_value)), '{}')
      INTO normalized_aliases
      FROM unnest(COALESCE(NEW.aliases, '{}')) AS alias_value;
    NEW.search_text := concat_ws(E'\n', NEW.name_key, array_to_string(normalized_aliases, E'\n'));
    NEW.updated_at := now();
    RETURN NEW;
END
$$;

CREATE TRIGGER companies_search_columns_before_write
BEFORE INSERT OR UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION zoop_companies_update_search_columns();
