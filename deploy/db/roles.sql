-- Give Supabase's auth roles the database password. Only roles that exist at
-- this point of the image's first-start setup may be listed here: an error
-- would stop the rest of the database setup.
\set pgpass `echo "$POSTGRES_PASSWORD"`
ALTER USER authenticator WITH PASSWORD :'pgpass';
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
