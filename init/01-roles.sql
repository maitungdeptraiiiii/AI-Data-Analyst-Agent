CREATE SCHEMA IF NOT EXISTS analysis;

CREATE ROLE ingest_rw LOGIN PASSWORD 'ingest_dev_password';
CREATE ROLE executor_ro LOGIN PASSWORD 'executor_dev_password';

GRANT CONNECT ON DATABASE analyst TO ingest_rw, executor_ro;
GRANT USAGE, CREATE ON SCHEMA analysis TO ingest_rw;
GRANT USAGE ON SCHEMA analysis TO executor_ro;

ALTER DEFAULT PRIVILEGES
    FOR ROLE ingest_rw
    IN SCHEMA analysis
    GRANT SELECT ON TABLES TO executor_ro;

ALTER ROLE executor_ro SET default_transaction_read_only = on;
ALTER ROLE executor_ro SET statement_timeout = '10s';
ALTER ROLE executor_ro SET lock_timeout = '3s';

