#!/bin/sh
# AutoRoot V4 runs /var/addons/<name>/init/start.sh as root in the background.
BASE=/var/rootdata/q10_volte
[ -f "$BASE/enabled" ] || exit 0
attempt=0
while [ ! -f /tmp/root.done ] && [ "$attempt" -lt 60 ]; do
    sleep 2
    attempt=$((attempt + 1))
done
[ -f /tmp/root.done ] || exit 1
/proc/boot/pathtrust "!$BASE/device/run.sh" || exit 1
exec /bin/sh "$BASE/device/run.sh" start
