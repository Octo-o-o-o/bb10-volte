#!/bin/sh
set -eu
moc /work/mobile/native/src/mobilecontroller.h -o /tmp/bb10-controller-moc.cpp
moc /work/tests/native_controller/bb/cascades/Application -o /tmp/bb10-application-moc.cpp
entry_sha="$(sha256sum /work/mobile/runtime/entry.py | cut -d ' ' -f 1)"
printf '#define BB10_ENTRY_SHA256 "%s"\n#define BB10_MOBILE_VERSION "0.1.0.17"\n#define BB10_PUBLIC_KEY_ID "test"\n' "$entry_sha" > /tmp/bundle_identity.h
qt_flags="$(pkg-config --cflags --libs Qt5Core Qt5Network)"
# Intentional splitting: pkg-config emits individual compiler arguments.
g++ -std=c++11 -fPIC -Wall -Wextra -Wno-deprecated-declarations \
  -I/work/tests/native_controller \
  -I/work/mobile/native/src -I/tmp \
  /work/mobile/native/src/mobilecontroller.cpp /tmp/bb10-controller-moc.cpp /tmp/bb10-application-moc.cpp \
  /work/tests/native_controller/controller_test.cpp \
  $qt_flags -lcrypto -o /tmp/bb10-controller-test
g++ -std=c++11 -fPIC -Wall -Wextra -Wno-deprecated-declarations \
  -I/work/tests/native_controller -I/work/mobile/native/src -I/tmp \
  /work/mobile/native/src/mobilecontroller.cpp /tmp/bb10-controller-moc.cpp /tmp/bb10-application-moc.cpp \
  /work/tests/native_controller/network_test.cpp \
  $qt_flags -lcrypto -o /tmp/bb10-network-test
/tmp/bb10-controller-test
exec /tmp/bb10-network-test
