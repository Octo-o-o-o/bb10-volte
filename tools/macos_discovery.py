"""Bounded anonymous USB metadata through the macOS system HTTP client."""
import ipaddress
import subprocess

LIMIT = 131072


def read(peer, source):
    # The caller derives this /30 from the sole attached BlackBerry interface.
    # Reject direct calls which could turn discovery into a LAN/Internet fetch.
    try:
        address, local = ipaddress.IPv4Address(peer), ipaddress.IPv4Address(source)
        if not address.is_link_local or int(local) % 4 != 2 or int(address) != int(local) - 1:
            return b''
    except (ValueError, TypeError):
        return b''
    command = ['/usr/bin/curl', '--disable', '--silent', '--show-error',
               '--proxy', '', '--noproxy', '*', '--proto', '=http',
               '--interface', str(local), '--connect-timeout', '4', '--max-time', '5',
               '--max-filesize', str(LIMIT), '--user-agent', 'QNXWebClient/1.0',
               '--header', 'Connection: close', '--write-out', '\n%{http_code}',
               'http://' + str(address) + '/cgi-bin/discovery.cgi']
    # -q/--disable is first: user curlrc files cannot add authentication,
    # redirects, output files or proxies. No shell, cookies or credentials.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        data = child.stdout.read(LIMIT + 5)
        if len(data) > LIMIT + 4:
            child.kill()
            child.wait(timeout=6)
            return b''
        if child.wait(timeout=6) != 0 or not data.endswith(b'\n200'):
            return b''
    return data[:-4]
