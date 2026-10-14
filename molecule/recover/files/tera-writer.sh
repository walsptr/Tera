#!/bin/bash
# Molecule recover scenario (test only): insert rows on a remote node over TCP and record every
# id the server acknowledged (autocommit: acknowledged = committed). Used by recover and
# recover-poweroff.
set -u
host=$1
out=$2
: > "$out"
while true; do
  if id=$(mariadb --defaults-extra-file=/root/tera-writer.cnf --connect-timeout=2 -h "$host" -N -B \
      -e "INSERT INTO app.recover_t (v) VALUES (1); SELECT LAST_INSERT_ID();" 2>/dev/null); then
    echo "$id" >> "$out"
    # fsync the log: the power-off variant resets the VM without flushing the page cache.
    sync "$out"
  fi
  sleep 0.05
done
