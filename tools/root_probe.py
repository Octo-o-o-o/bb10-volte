"""Read only the effective UID. Run as a trusted file on BB10 Python 3.2."""
import json
import os


if __name__ == '__main__':
    print(json.dumps({'schema': 1, 'euid': os.geteuid()}))
