# Native controller isolation test

This test compiles the production controller against Qt and runs its real event
loop, process handling and settings. It checks cold launch, cached observations,
pending operations, request failures and call-confirmation reconciliation. It
does not render Cascades controls or replace QNX and physical-device acceptance.

Build the disposable image from this directory, then run it with this repository
mounted read-only at `/work` and an executable temporary filesystem:

```sh
docker build -t bb10-controller-qt-harness tests/native_controller
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --read-only --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m --user 65534:65534 \
  --mount type=bind,source="$PWD",target=/work,readonly -w /tmp \
  --mount type=bind,source="$PWD/tests/native_controller/fake-root.sh",target=/bin/__root,readonly \
  --entrypoint sh bb10-controller-qt-harness /work/tests/native_controller/run.sh
```

The image installs an inert fake `/bin/__root` solely inside the disposable
container. Never install that fake on the host or a phone. The image starts from
a pinned base image, while its Debian package repository is not a pinned snapshot.
The explicit helper mount keeps the test in sync with the checkout even when an
existing local image was built with an older fake helper.

The following separate process test uses the actual job and management record
locks against disposable `/tmp` files. It needs UID 0 inside the isolated
container because the production management lock checks its owner:

```sh
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --read-only --tmpfs /tmp:rw,exec,nosuid,nodev,size=64m \
  --mount type=bind,source="$PWD",target=/work,readonly \
  --entrypoint python3 bb10-controller-qt-harness \
  /work/tests/native_controller/context_race.py --after
```

Run `tests/native_controller/job_observation_race.py` in the same UID 0
container to check completed-job and reboot-transition observations against a
concurrent submit using the actual POSIX job lock and temporary journals.
