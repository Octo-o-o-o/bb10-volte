#!/bin/sh
# The original Root loader never waits for network registration or a SIM.
BASE=/var/bb10_volte
[ -f "$BASE/enabled" ] || exit 0
export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHOME=/usr
export PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload
(
    count=0
    while [ ! -f /tmp/root.done ] && [ ! -f "$BASE/root-v2" ]; do
        count=$((count + 1))
        [ "$count" -lt 120 ] || exit 1
        sleep 1
    done
    for name in native profiles device_info compatibility service ims_image radio_api telecom_native telecom_dca carrier_policy unified_service unified_dca unified_install unified_migrate unified_operator_name unified_own_number; do
        /proc/boot/pathtrust "!$BASE/device/$name.py" || exit 1
    done
    /usr/bin/python3.2 "$BASE/device/unified_service.py" boot
) >> "$BASE/state/boot.log" 2>&1 &
exit 0
