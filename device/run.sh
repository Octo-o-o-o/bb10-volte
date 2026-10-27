#!/bin/sh
BASE=/var/rootdata/q10_volte
export LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot
export PYTHONHOME=/usr
export PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload
for name in service.py native.py ims_image.py radio_api.py install.py; do
    /proc/boot/pathtrust "!$BASE/device/$name" || exit 1
done
exec /usr/bin/python3.2 "$BASE/device/service.py" "$1"
