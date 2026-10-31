#!/bin/sh
# AutoRoot v4 runs /var/addons/<name>/init/start.sh as root in the background.
BASE=/var/rootdata/passport_volte_research
[ -f "$BASE/enabled" ] || exit 0
attempt=0
while [ ! -f /tmp/root.done ] && [ "$attempt" -lt 60 ]; do
    sleep 2
    attempt=$((attempt + 1))
done
[ -f /tmp/root.done ] || exit 1
export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHOME=/usr
export PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload
for name in native profiles device_info compatibility service ims_image radio_api telecom_attach telecom_dca telecom_native; do
    /proc/boot/pathtrust "!$BASE/device/$name.py" || exit 1
done
/proc/boot/pathtrust "!$BASE/passport_volte_phone.py" || exit 1
(umask 077; : > "$BASE/boot-addon.log")
exec /usr/bin/python3.2 "$BASE/passport_volte_phone.py" boot >> "$BASE/boot-addon.log" 2>&1
