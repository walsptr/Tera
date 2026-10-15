#!/bin/bash
# Molecule loadbalancer scenario (test only): record every 0.2 s whether this node holds the VIP.
# Line: "<epoch> 1" (holds it) or "<epoch> 0". Appends, so a restart after a reboot keeps the log.
set -u
vip=$1
log=$2
while true; do
  if ip -o -4 addr show | grep -q " ${vip}/"; then held=1; else held=0; fi
  echo "$(date +%s.%N) $held" >> "$log"
  sleep 0.2
done
