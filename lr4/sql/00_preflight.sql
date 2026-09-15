\set ON_ERROR_STOP on

SELECT current_setting('server_version_num')::integer BETWEEN 170000 AND 179999
    AS supported_server_version \gset

\if :supported_server_version
\else
    \echo 'LR4 requires PostgreSQL 17.x'
    \quit 3
\endif

SELECT EXISTS (
    SELECT 1
    FROM pg_available_extensions
    WHERE name = 'plpython3u'
) AS plpython_available \gset

\if :plpython_available
\else
    \echo 'The server-side plpython3u package is not available'
    \quit 3
\endif

CREATE EXTENSION IF NOT EXISTS plpython3u;
CREATE SCHEMA IF NOT EXISTS lr4;

