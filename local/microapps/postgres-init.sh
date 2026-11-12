#!/bin/sh
# First start of the local micro-application profile's Postgres (runs once,
# from /docker-entrypoint-initdb.d, as the bootstrap superuser).
#
# Roles:
#   ics                   owner of the ICS metadata database; CREATEDB only
#                         because the backend tests create ics_test_* copies.
#   ics_apps_provisioner  trusted provisioner of micro-application schemas and
#                         roles. CREATEROLE lets it manage only the roles it
#                         creates (PostgreSQL 16+). CREATEDB is a local-profile
#                         convenience for the tests' ics_apps_test_* copies.
# The broker has no login of its own: it connects with each asset's runtime role.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ics LOGIN CREATEDB PASSWORD '${ICS_PG_PASSWORD}';
CREATE ROLE ics_apps_provisioner LOGIN CREATEROLE CREATEDB PASSWORD '${ICS_APPS_PROVISIONER_PASSWORD}';
-- Reads every app's data (granted per schema by ICS), never writes.
CREATE ROLE ics_apps_reader LOGIN NOINHERIT PASSWORD '${ICS_APPS_READER_PASSWORD}';
-- Cuts the sessions of a deleted app's runtime role before dropping it.
GRANT pg_signal_backend TO ics_apps_provisioner;
CREATE DATABASE ics OWNER ics TEMPLATE template0;
REVOKE ALL ON DATABASE ics FROM PUBLIC;
CREATE DATABASE ics_apps OWNER ics_apps_provisioner TEMPLATE template0;
REVOKE ALL ON DATABASE ics_apps FROM PUBLIC;
GRANT CONNECT ON DATABASE ics_apps TO ics_apps_reader;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname ics_apps <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO ics_apps_provisioner;
SQL

