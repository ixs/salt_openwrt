# Import Python Libs
from __future__ import absolute_import, print_function, unicode_literals
import logging

# Import Salt Libs
import salt.utils.platform

log = logging.getLogger(__name__)

__virtualname__ = 'openwrt'

def __virtual__():
    '''
    Will load for the openwrt proxy minions.
    '''
    try:
        if salt.utils.platform.is_proxy() and \
           __opts__['proxy']['proxytype'] == 'openwrt':
            return __virtualname__
    except KeyError:
        pass

    return False, 'The openwrt execution module can only be loaded for openwrt proxy minions.'


def update_pkgs():
    '''
    Update the list of available packages
    '''
    out, _, ret = __proxy__['ssh.ssh_check']('opkg update')
    if ret == 0:
        return True
    else :
        return False


def list_pkgs():
    '''
    Retrieve a list of installed packages from the openwrt host
    '''
    pkgs = {}
    for line, _, ret in __proxy__['openwrt.ssh_check']('opkg list-installed').split('\n'):
        pkg, version = line.split(' - ')
        pkgs[pkg] = version
    return pkgs


def remove_pkg(pkg):
    '''
    Remove an installed package
    '''
    out, _, ret = __proxy__['openwrt.ssh_check']('opkg remove %s' % (pkg,))
    if ret == 0:
        return True
    else :
        return False

def network_restart():
    '''
    Restart the network, reconfigures all interfaces
    '''
    out = __proxy__['openwrt.ubus']('network', 'restart')
    if ret == 0:
        return True
    else :
        return False


def network_reload():
    '''
    Reload the network, reload interfaces as needed
    '''
    out = __proxy__['openwrt.ubus']('network', 'reload')
    if ret == 0:
        return True
    else :
        return False


def interface_list():
    '''
    Fetch a list of existing interfaces
    '''
    intfs = []
    out, _, ret = __proxy__['openwrt.ssh_check']('ubus list')
    if ret == 0:
        for line in out.split('\n'):
            if line.startswith('network.interface.'):
                intfs.append('.'.join(line.split('.')[2:]))
    else :
        return False


def network_dev_status(intf):
    '''
    Dump hardware state and counters of given network device ifname
    '''
    return __proxy__['openwrt.ubus']('network.device', 'status', {'name': intf})


def interface_status(intf):
    '''
    Dump network configuration of given network device ifname
    '''
    return __proxy__['openwrt.ubus']('network.interface.%s' % (intf,), 'status')


def config_dump():
    '''
    Dump the whole uci config tree
    '''
    out, err, ret =  __proxy__['openwrt.ssh_check']('uci show')
    if ret != 0:
        return false
    return _parse_uci(out)


def _parse_uci(data):
    '''
    Parse the UCI output into a dict
    '''
    uci = {}
    for line in data.split('\n'):
        key, value = line.split('=', 1)
        path = key.split('.')
        uci['key'] = value
    return uci


def run(command):
    '''
    Run command
    '''
    out, err, ret = __proxy__['openwrt.ssh_check'](command)
    return ({'stdout': out, 'stderr': err, 'exitcode': ret})


def reboot():
    '''
    Reboot openwrt device
    '''
    __proxy__['openwrt.ubus']('system', 'reboot')
    return True
