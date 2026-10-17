#!/bin/bash
# Molecule upgrade scenario (test only): write through the VIP every ~0.1 s, one new connection per write.
# Each line: "<epoch> ok <node>" or "<epoch> fail <error>". Stops when /root/tera-writer.stop exists.
# Usage: writer.sh <vip> <log>
set -euo pipefail
vip="$1"
log="$2"
rm -f /root/tera-writer.stop
: >"$log"
while [[ ! -e /root/tera-writer.stop ]]; do
  t="$(date +%s.%N)"
  if out="$(mariadb --defaults-extra-file=/root/tera-test.cnf --connect-timeout=2 -h "$vip" -N -B \
    -e "INSERT INTO app.upgrade_writes (h) VALUES (@@hostname); SELECT @@hostname" 2>&1)"; then
    echo "$t ok $out" >>"$log"
  else
    echo "$t fail ${out//$'\n'/ }" >>"$log"
  fi
  sleep 0.1
done
