# Pinned native Mac tool repair

The pinned upstream bb10mt tool could finish writing a signed image, submit its
signature, print `Done`, request the normal reboot, and then fail with
`Init: LIBUSB_ERROR_OTHER`. On the Q20 test device, USB networking returned and
the owner observed the language selection screen. The original failed stage
receipt remains a failure; this repair does not reinterpret it as a successful
flash.

In upstream commit
[`d45b66b`](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/ramloader.pas#L896-L923),
`TRamLoader.RebootPhone` closes its existing connections after requesting reboot,
then creates a new USB context outside the exception handler. Opening that new
connection is redundant. Its constructor can raise after the phone has already
rebooted. The source-equivalent change is:

```diff
--- a/ramloader.pas
+++ b/ramloader.pas
@@ -915,10 +915,3 @@
     SafeCloseAndFree(fBB);
   end;
-
-  fBB := TBBUSB.Create;
-  try
-    fBB.Open([1, $8001]);
-  except
-  end;
-  SafeCloseAndFree(fBB);
 end;
```

The upstream source is provided under its
[GNU GPL version 3 license](https://github.com/bb10root/bb10mt/blob/d45b66ba9594a2912dd005e3607da1d4825fb06e/LICENSE).
The original source and this change describe the modified function. Original
credits remain with bb10mt's authors.

`materials/macos-root-tools.json` pins the original complete executable hashes,
every replaced byte, and the resulting complete executable hashes. Preparation
applies the edits locally to the verified upstream artifact. A mismatch fails
before the result is used. The ARM64 edit updates the changed page hash in the
existing ad-hoc CodeDirectory; `codesign --verify --strict` passed on the derived
executable. The Intel input is unsigned.

The original and derived ARM64 and Intel function bodies were emulated for all
eight combinations of existing loader/USB objects and exception-return state
per architecture. All 16 comparisons preserved the original reboot and cleanup
call sequence and restored the stack; only the redundant create/open/cleanup
tail was omitted. External USB calls were stubs, so this check is not hardware
acceptance. Image writing, signature verification, password handling and the
stage success classifier are unchanged. Real device results are tracked in
[the acceptance record](SMS-ROOT-ACCEPTANCE-2026-11-01.md).
