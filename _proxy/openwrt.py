from __future__ import absolute_import, print_function, unicode_literals

# Import Python Libs
import logging
import re

# Import Salt Libs
import salt.exceptions
import salt.utils.stringutils
import salt.utils.json
from salt.utils.vt_helper import SSHConnection
from salt.utils.vt import TerminalException
from salt.exceptions import CommandExecutionError

# This must be present or the Salt loader won't load this module.
__proxyenabled__ = ['openwrt']

# Variables are scoped to this module so we can have persistent data.
GRAINS_CACHE = {}
DETAILS = {}

# Set up logging
log = logging.getLogger(__file__)

# Define the module's virtual name
__virtualname__ = 'openwrt'


def __virtual__():
    '''
    Only return if all the modules are available.
    '''
    return __virtualname__


def init(opts):
    '''
    Required.
    Can be used to initialize the server connection.
    '''
    if opts is None:
        opts = __opts__

    try:
        DETAILS['server'] = SSHConnection(
            host=opts['proxy']['host'],
            username=opts['proxy']['username'],
            password=opts['proxy']['password'],
            key_accept=opts['proxy'].get('key_accept', False),
            ssh_args=opts['proxy'].get('ssh_args', ''),
            prompt='.+[#$]')
        log.info('SSH Connection established.')
        out, err = DETAILS['server'].sendline('id')
        DETAILS['initialized'] = True

    except TerminalException as e:
        log.error(e)
        return False


def initialized():
    '''
    Since grains are loaded in many different places and some of those
    places occur before the proxy can be initialized, return whether
    our init() function has been called
    '''
    return DETAILS.get('initialized', False)


def ping():
    '''
    Required.
    Ping the device on the other end of the connection
    '''
    try:
        DETAILS['server'].sendline('id')
        return True
    except TerminalException as e:
        log.error(e)
        return False


def grains(**kwargs):
    '''
    Get grains for minion.
    .. code-block: bash
        salt '*' openwrt.cmd grains
    '''
    if len(GRAINS_CACHE) == 0:
        system = ubus('system', 'info')
        board = ubus('system', 'board')
        netdev = ubus('network.device', 'status')
        netif = ubus('network.interface', 'dump')

        GRAINS_CACHE['mem_total'] = system['memory']['total'] // 1024 // 1024
        GRAINS_CACHE['swap_total'] = system['swap']['total'] // 1024 // 1024
        GRAINS_CACHE['cpuarch'] = ssh_oneshot('uname -m')
        GRAINS_CACHE['cpumodel'] = board['system']
        GRAINS_CACHE['kernel'] = ssh_oneshot('uname -s')
        GRAINS_CACHE['kernelrelease'] = board['kernel']
        GRAINS_CACHE['kernelversion'] = ssh_oneshot('uname -v')
        GRAINS_CACHE['fqdn'] = board['hostname']
        GRAINS_CACHE['manufacturer'], GRAINS_CACHE['productname'] = board['model'].split(' ', 1)
        GRAINS_CACHE['os'] = board['release']['distribution']
        GRAINS_CACHE['os_family'] = 'openwrt'
        GRAINS_CACHE['oscodename'] = board['release']['codename']
        GRAINS_CACHE['osfullname'] = board['release']['description']
        GRAINS_CACHE['osrelease'] = board['release']['version']
        GRAINS_CACHE['osmajorrelease'] = board['release']['version'].split('.')[0]
        GRAINS_CACHE['osrelease_info'] = board['release']['version'].split('.')
        GRAINS_CACHE['osfinger'] = '%s-%s' % (GRAINS_CACHE['os'], GRAINS_CACHE['osmajorrelease'])

        GRAINS_CACHE['ip_gw'] = False
        GRAINS_CACHE['ipv6_gw'] = False
        dns = {'domain': [], 'ip4_nameservers': [], 'ip6_nameservers': [], 'nameservers': [], 'options': [], 'search': [], 'sortlist': []}
        hwaddr_interfaces = {}
        ip4_interfaces = {}
        ip6_interfaces = {}
        ip_interfaces = {}
        ipv4 = {}
        ipv6 = {}
        for dev, i in netdev.iteritems():
            hwaddr_interfaces[dev] = i['macaddr']
        for i in netif['interface']:
            try:
                ip4_interfaces.update({ i['device']: [ x['address'] for x in i['ipv4-address'] ] })
            except KeyError:
                pass
            try:
                ip6_interfaces.update({ i['device']: [ x['address'] for x in i['ipv6-address'] ] })
            except KeyError:
                pass
            for item in [('dns-server', 'nameservers'), ('dns-search', 'search')]:
                if len(i[item[0]]) > 0:
                    dns[item[1]].extend(i[item[0]])
            for route in i['route']:
                if route['target'] == '0.0.0.0':
                    GRAINS_CACHE['ip4_gw'] = route['nexthop']
                    GRAINS_CACHE['ip_gw'] = True
                if route['target'] == '::/0':
                    GRAINS_CACHE['ip6_gw'] = route['nexthop']
                    GRAINS_CACHE['ipv6_gw'] = True

        GRAINS_CACHE['dns'] = dns
        GRAINS_CACHE['hwaddr_interfaces'] = hwaddr_interfaces
        GRAINS_CACHE['ip4_interfaces'] = ip4_interfaces
        GRAINS_CACHE['ip6_interfaces'] = ip6_interfaces
#        GRAINS_CACHE['ip4'] = [y for y in x for x in GRAINS_CACHE['ip4_interfaces'].values() if x]
#        GRAINS_CACHE['ip6'] = [y for y in x for x in GRAINS_CACHE['ip6_interfaces'].values() if x]

        archinfo = {}
        for line in ssh_oneshot('opkg print-architecture').splitlines():
            if line.startswith('arch'):
                _, arch, priority = line.split()
                archinfo[arch.strip()] = int(priority.strip())

        # Return osarch in priority order (higher to lower)
        osarch = sorted(archinfo, key=archinfo.get, reverse=True)
        GRAINS_CACHE['osarch'] = osarch

        # mtd
        try:
            mtd_total_size = 0
            flash_layout = {}
            for part in ssh_file_content('/proc/mtd').split('\n')[1:]:
                dev, size, erasesize, name = part.split()
                dev = dev[:-1]
                size = int(size, 16)
                mtd_total_size += size
                flash_layout[dev] = {'name': name, 'size': size}
            GRAINS_CACHE['flash'] = {'partitions': flash_layout, 'total_size': mtd_total_size / 1024 / 1024}
        except ValueError:
            pass

    return GRAINS_CACHE


def grains_refresh(**kwargs):
    '''
    Refresh the grains for the OpenWRT device.
    .. code-block: bash
        salt '*' openwrt.cmd grains_refresh
    '''
    GRAINS_CACHE = {}
    return grains(**kwargs)


def ubus(path, method, message = {}):
    '''
    Call a remote ubus method
    '''
    command = 'ubus call %s %s \'%s\'' % (path, method, salt.utils.json.dumps(message))
    out, _ = ssh_cmd(command)
    return salt.utils.json.loads(out)

def ssh_oneshot(command):
    '''
    Run simple ssh command, ignoring errors
    '''
    out, _ = ssh_cmd(command)
    return out


def ssh_cmd(command):
    '''
    Run cmd on the remote system
    '''
    try:
        out, err = DETAILS['server'].sendline(command)
        out = "\n".join(out.split('\n')[1:-1])
        return out, err
    except TerminalException as e:
        log.error(e)
        return False


def ssh_check(command):
    '''
    Run cmd on the remote system and fetch exit code
    '''
    try:
        out, err = DETAILS['server'].sendline('%s; echo $?' % (command,))
        out = "\n".join(out.split('\n')[1:-1])
        out, _, ret = out.rpartition('\n')
        return out, err, int(ret)
    except TerminalException as e:
        log.error(e)
        return False


def ssh_file_content(filename):
    '''
    Fetch the content of a file on the remote system
    '''
    data, _ = ssh_cmd('cat %s' % (filename,))
    return data

def shutdown(opts):
    '''
    Disconnect
    '''
    DETAILS['server'].close_connection()
