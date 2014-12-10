import sys
import os
import ConfigParser
from netaddr import *

import debug
import sql
import vmjson

vulnautolist = []
uidcache = []
dbconn = None

class VulnAutoEntry(object):
    def __init__(self, name):
        self.name = name
        self.mincvss = None

        self._match_ip = None
        self._match_net = None

    def add_match(self, val):
        if '/' in val:
            self._match_net = IPNetwork(val)
        else:
            self._match_ip = IPAddress(val)

    def ip_test(self, ipstr):
        ip = IPAddress(ipstr)

        # First try the IP
        if self._match_ip != None:
            if self._match_ip == ip:
                return 32

        if ip in self._match_net:
            return self._match_net.netmask.bits().count('1')

        return -1

class WorkflowElement(object):
    STATUS_NONE = 0
    STATUS_ESCALATED = 1

    def __init__(self):
        self.workflow_id = None
        self.vulnerability = None
        self.lasthandled = None
        self.contact = None
        self.status = None

class vulnerability(object):
    def __init__(self):
        self.sitename = None
        self.assetid = None
        self.ipaddr = None
        self.hostname = None
        self.macaddr = None
        self.title = None
        self.discovered_date = None
        self.discovered_date_unix = None
        self.cves = None
        self.cvss = None
        self.rhsa = None
        self.vid = None
        self.known_exploits = None
        self.known_malware = None

    def __str__(self):
        buf = '----- %d %s | %s | %s\n' \
            'sitename: %s\n' \
            'hostname: %s\n' \
            'macaddr: %s\n' \
            'discovered: %s\n' \
            '----' % (self.assetid, self.ipaddr, self.title, self.vid,
                self.sitename, self.hostname, self.macaddr,
                self.discovered_date)
        return buf

def vuln_reset_uid_cache():
    global uidcache
    uidcache = []

def expire_hosts():
    dbconn.expire_hosts(uidcache)

def escalate_vulns(escdir):
    ret = dbconn.asset_list()
    debug.printd('processing %d assets' % len(ret))

    for i in ret:
        wfes = dbconn.get_workflow(i)

        for w in wfes:
            # Only escalate things that haven't been handled yet
            if w.status != WorkflowElement.STATUS_NONE:
                continue

            # Create JSON event from the element
            jv = vmjson.wf_to_json(w)

def asset_unique_id(address, mac, hostname, aid):
    if mac == '':
        u_mac = 'NA'
    else:
        u_mac = mac
    if hostname == '':
        u_hostname = 'NA'
    else:
        u_hostname = hostname
    ret = '0|%s|%s|%s|%s' % (aid, address, u_hostname, u_mac)
    debug.printd('using identifier %s' % ret)
    return ret

def vuln_auto_finder(address, mac, hostname):
    cand = None
    last = -1
    for va in vulnautolist:
        ret = va.ip_test(address)
        if ret == -1:
            continue
        if ret > last:
            cand = va
            last = ret
    if cand != None:
        debug.printd('using VulnAutoEntry %s (score: %d)' % (cand.name, last))
    else:
        debug.printd('unable to match automation handler')
    return cand

def vuln_proc_pipeline(vlist, aid, address, mac, hostname):
    global uidcache

    debug.printd('vulnerability process pipeline for asset id %d' % aid)
    vauto = vuln_auto_finder(address, mac, hostname)
    if vauto == -1:
        debug.printd('skipping pipeline for asset id %d, no handler' % aid)
        return

    uid = asset_unique_id(address, mac, hostname, aid)
    if uid not in uidcache:
        uidcache.append(uid)

    # XXX We will probably want to add something here to search and update
    # any existing references for this asset where we had less information,
    # this will likely need some sort of partial matching on fields.

    # Make sure the asset exists in the database, if not add it
    dbassetid = dbconn.add_asset(uid, aid, address, mac, hostname)
    debug.printd('using db asset %d' % dbassetid)

    for v in vlist:
        # We don't want to look at everything, query the handlers minimum
        # CVSS value to see if we should proceed
        if v.cvss >= vauto.mincvss:
            debug.printd('processing vulnerability %s' % v.vid)
            dbconn.add_vulnerability(v, dbassetid)
        else:
            debug.printd('skipping vulnerability %s as it does not meet ' \
                'minimum cvss score' % v.vid)

def load_vulnauto(dirpath, vmdbconn):
    global dbconn

    debug.printd('reading vulnerability automation data...')
    dbconn = vmdbconn
    dirlist = os.listdir(dirpath)
    for i in dirlist:
        load_vulnauto_list(os.path.join(dirpath, i))

def load_vulnauto_list(path):
    debug.printd('reading automation data from %s' % path)
    cp = ConfigParser.SafeConfigParser()
    cp.read(path)

    for s in cp.sections():
        n = VulnAutoEntry(s)
        for k, v in cp.items(s):
            if k == 'mincvss':
                n.mincvss = float(v)
                pass
            elif k == 'match':
                n.add_match(v)
            elif k == 'matchon':
                # Unused right now
                pass
            else:
                sys.stderr.write('vulnauto option %s not available under ' \
                    '%s\n' % (k, s))
                sys.exit(1)
        vulnautolist.append(n)
            
