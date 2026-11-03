#!/bin/sh
cat > /tmp/bb10-controller-harness/last-command
printf 'request\n' >> /tmp/bb10-controller-harness/calls
if [ -e /tmp/bb10-controller-harness/hang ]; then
    exec sleep 60
fi
if [ -e /tmp/bb10-controller-harness/progress ]; then
    printf 'noise\nBB10_PRO'
    : > /tmp/bb10-controller-harness/progress-started
    while [ ! -e /tmp/bb10-controller-harness/progress-release ]; do sleep 0.05; done
    printf 'GRESS:1\n'
    while [ ! -e /tmp/bb10-controller-harness/progress-finish ]; do sleep 0.05; done
elif [ -e /tmp/bb10-controller-harness/noise ]; then
    : > /tmp/bb10-controller-harness/noise-started
    while [ ! -e /tmp/bb10-controller-harness/noise-release ]; do sleep 0.05; done
    printf 'BB10_PROGRESS:2\nnoise\n'
    while [ ! -e /tmp/bb10-controller-harness/noise-finish ]; do sleep 0.05; done
fi
if [ -e /tmp/bb10-controller-harness/report-wait ]; then
    while [ ! -e /tmp/bb10-controller-harness/report-ready ]; do sleep 0.05; done
fi
cat /tmp/bb10-controller-harness/response.json
