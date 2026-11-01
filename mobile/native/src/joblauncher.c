/* BB10/QNX 6.6: an owned job outlives the Cascades application group. */
#include <sys/stat.h>
#include <spawn.h>
#include <fcntl.h>
#include <unistd.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char prefix[] = "/var/bb10_volte-mobile/snapshots/";
static const char suffix[] = "/runtime/job-launcher";

static int hexadecimal(const char *text, size_t length)
{
    size_t i;
    for (i = 0; i < length; ++i)
        if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f')))
            return 0;
    return 1;
}

static int private_directory(const char *path)
{
    struct stat value;
    return lstat(path, &value) == 0 && S_ISDIR(value.st_mode) &&
           value.st_uid == 0 && (value.st_mode & 0077) == 0;
}

int main(int argc, char *argv[])
{
    char self[PATH_MAX], folder[PATH_MAX], script[PATH_MAX];
    struct stat value;
    struct inheritance inherit;
    int descriptor, map[3];
    pid_t child;
    const size_t folder_length = sizeof(prefix) - 1 + 64;
    char *environment[] = {
        "PATH=/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin",
        "LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot",
        "PYTHONHOME=/usr", "PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload",
        "PYTHONDONTWRITEBYTECODE=1", "LANG=C", "TERM=dumb", NULL
    };
    char *arguments[] = {"/usr/bin/python3.2", "-B", script, NULL, NULL, NULL};
    if (argc != 3 || geteuid() != 0 || strlen(argv[1]) != 32 || strlen(argv[2]) != 32 ||
        !hexadecimal(argv[1], 32) || !hexadecimal(argv[2], 32)) return 64;
    if (!realpath(argv[0], self) || strcmp(self, argv[0]) != 0 ||
        strlen(self) != folder_length + sizeof(suffix) - 1 ||
        strncmp(self, prefix, sizeof(prefix) - 1) != 0 ||
        !hexadecimal(self + sizeof(prefix) - 1, 64) || strcmp(self + folder_length, suffix) != 0)
        return 65;
    memcpy(folder, self, folder_length);
    folder[folder_length] = '\0';
    if (!private_directory("/var/bb10_volte-mobile") ||
        !private_directory("/var/bb10_volte-mobile/snapshots") || !private_directory(folder)) return 66;
    snprintf(script, sizeof(script), "%s/runtime", folder);
    if (!private_directory(script)) return 66;
    snprintf(script, sizeof(script), "%s/runtime/background_entry.py", folder);
    if (lstat(script, &value) != 0 || !S_ISREG(value.st_mode) || value.st_uid != 0 ||
        (value.st_mode & 0077) != 0 || value.st_nlink != 1) return 66;
    descriptor = open("/dev/null", O_RDWR);
    if (descriptor == -1) return 67;
    map[0] = map[1] = map[2] = descriptor;
    memset(&inherit, 0, sizeof(inherit));
    inherit.flags = SPAWN_NEWAPP | SPAWN_SETSID | SPAWN_NOZOMBIE;
    arguments[3] = argv[1];
    arguments[4] = argv[2];
    /* fd_count=3 closes every inherited descriptor above stderr in the child. */
    child = spawn(arguments[0], 3, map, &inherit, arguments, environment);
    close(descriptor);
    if (child == -1) return 68; /* No fallback to the app's application group. */
    printf("%ld\n", (long)child);
    return 0;
}
