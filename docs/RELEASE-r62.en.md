# Windows r61 and mobile 0.2.5.0

- Windows can choose another folder for automatic downloads started afterward, and for new Root or stock-upgrade preparation. Leaving it unset keeps the original location. Connection, installation and status do not depend on the choice.
- Choosing a folder does not take over the main window, does not move existing files, and does not redirect a download, preparation or flash that has already started. If the folder is missing, a symlink or junction, inside the program or personal directory, or not writable, new files stay on the original path and the window says so.
- Cleanup is a checklist. Each item shows its purpose and size, and nothing is checked by default. Keys, connection files, logs, backups and flash records are never listed. Items that are still downloading, preparing or flashing cannot be checked. After Root or the stock system has been written, the same window can open for that run and defaults to keeping the files. If the window cannot open, the finished result remains.

Mobile stays 0.2.5.0, with no new phone payload. macOS downloads remain the frozen r43 release. This version adds no call, message or data acceptance.
