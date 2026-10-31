#!/bin/sh
BASE=/var/rootdata/q10_volte
test -f "$BASE/enabled" || exit 0
test -f "$BASE/state/telecom-autostart-acceptance.json" || exit 0
attempt=0
while [ ! -f /tmp/root.done ] && [ "$attempt" -lt 60 ]; do
    sleep 2
    attempt=$((attempt + 1))
done
test -f /tmp/root.done || exit 1
for file in native.py profiles.py device_info.py autostart_evidence.py operator_name.py; do
    /proc/boot/pathtrust "!$BASE/device/$file" || exit 1
done
LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot \
PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/usr PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload \
/usr/bin/python3.2 "$BASE/device/operator_name.py" start
