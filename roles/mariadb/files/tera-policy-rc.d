#!/bin/sh
# tera-policy-rc.d: installed by tera upgrade (ADR 0015) while the MariaDB packages are upgraded, removed
# right after. Refuses only MariaDB, so the package cannot start it behind Tera's back; every other service
# is allowed. A copy left by an interrupted run is removed by the next tera deploy, reconfigure or upgrade.
case "$1" in
  mariadb | mariadb.service | mysql | mysql.service) exit 101 ;;
esac
exit 0
