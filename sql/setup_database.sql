-- One-time setup: create the project login role and database.
-- Run as a superuser through scripts/setup_database.sh, which passes the psql variables
-- app_user, app_password and app_db from .env. Safe to re-run.

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- Keep the password in sync with .env if the role already existed.
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'app_user', :'app_password')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'app_db')
\gexec

\connect :"app_db"

-- The project role owns the public schema so it can create tables and views.
SELECT format('ALTER SCHEMA public OWNER TO %I', :'app_user')
\gexec
