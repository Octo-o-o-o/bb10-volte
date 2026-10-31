#!/bin/sh
# Invoked asynchronously after the existing AutoRoot-v2 script finishes.
BASE=/var/q20_volte
[ -f "$BASE/enabled" ] || exit 0
case "$(cat /pps/services/deviceproperties)" in
    *"modelnumber::SQC100-2"*) ;;
    *) exit 93 ;;
esac
export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHOME=/usr
export PYTHONPATH=$BASE/device:$BASE:/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload
for name in native.py profiles.py device_info.py compatibility.py service.py ims_image.py radio_api.py; do
    /proc/boot/pathtrust "!$BASE/device/$name" || exit 1
done
/proc/boot/pathtrust "!$BASE/q20_volte_phone.py" || exit 1
/proc/boot/pathtrust "!$BASE/q20_own_number_auto.py" || exit 1
for name in q20_telecom_carrier.py q20_telecom_dca_usage_phone.py q20_telecom_native_probe_phone.py; do
    /proc/boot/pathtrust "!$BASE/$name" || exit 1
done
exec /usr/bin/python3.2 "$BASE/q20_volte_phone.py" boot
