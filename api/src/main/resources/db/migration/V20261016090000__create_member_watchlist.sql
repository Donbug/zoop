CREATE TABLE member_watchlist (
    member_id text NOT NULL,
    company_id text NOT NULL,
    position integer NOT NULL,
    CONSTRAINT pk_member_watchlist PRIMARY KEY (member_id, company_id),
    CONSTRAINT uq_member_watchlist_position UNIQUE (member_id, position),
    CONSTRAINT ck_member_watchlist_position CHECK (position >= 0),
    CONSTRAINT fk_member_watchlist_member FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_member_watchlist_company FOREIGN KEY (company_id) REFERENCES companies (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX ix_member_watchlist_company ON member_watchlist (company_id);
