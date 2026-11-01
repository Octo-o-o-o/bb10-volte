# Feedback (for the next desktop release)

Each main step has **Problem / feedback** and **Open illustrated guide for this step**. The entry remains available during connection, drivers, first Root, OS upgrade, carrier installation, restart checks, call acceptance and recovery.

Open feedback, describe the problem, review the redacted preview, then save the ZIP. Send it through your existing contact channel or to `octoooo@octoooo.com`. The app does not upload or send anything automatically. A short summary can also be copied.

The ZIP contains `feedback.json`, `timeline.txt` and `README.txt`: the current step, app/platform versions, recent actions, failure codes, allowlisted checks, candidate binding and six native-file digests, current status text and available sanitized Root build failure excerpts. Successful retries preserve earlier errors, including across app restarts.

History covers the latest five recorded sessions since this feature was installed, with at most 400 events per session. Truncated sessions are marked. It cannot recover errors that older versions did not record. If local persistence fails, the dialog warns and can still export the current in-memory session.

Only allowlisted, redacted data reaches the private `feedback/` folder. Export does not traverse the private directory or include SSH material, passwords, phone identifiers, phone backups or raw SIP/device communication logs. Exception traces contain file basenames and line numbers, without local variables. Root build excerpts read only failure lines from the bounded tail of the current known `root-build.log`. Review any free-text note before sharing; do not enter credentials or phone numbers.

Local export works without a feedback server or an account and leaves sharing in the user's control. A future cloud receiver should have a separate explicit send action after preview, with a visible destination and outcome.

r15 includes the feedback entry shown in the website tutorial. Users of the older r14 without this entry should use **More → Export check report** and describe the failing step. That older report is primarily a current snapshot.

See the [implementation](../tools/feedback.py), [tests](../tests/test_feedback.py), and [recording guide](recordings/FIRST-USE-RECORDING.md).
