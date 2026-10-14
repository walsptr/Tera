#!/bin/bash
# Molecule reconfigure scenario (test only): sample the local wsrep state every 0.2 s.
# Line: "<epoch> <cluster_size> <cluster_status> <local_state>", or "<epoch> down".
set -u
log=$1
: > "$log"
query="SELECT MAX(IF(VARIABLE_NAME = 'WSREP_CLUSTER_SIZE', VARIABLE_VALUE, NULL)),
  MAX(IF(VARIABLE_NAME = 'WSREP_CLUSTER_STATUS', VARIABLE_VALUE, NULL)),
  MAX(IF(VARIABLE_NAME = 'WSREP_LOCAL_STATE', VARIABLE_VALUE, NULL))
  FROM information_schema.GLOBAL_STATUS"
while true; do
  ts=$(date +%s.%N)
  row=$(mariadb --connect-timeout=1 -N -B -e "$query" 2>/dev/null | tr '\t' ' ')
  echo "$ts ${row:-down}" >> "$log"
  sleep 0.2
done
