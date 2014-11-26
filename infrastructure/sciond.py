"""
sciond.py

Copyright 2014 ETH Zurich

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from lib.packet.host_addr import IPv4HostAddr
from lib.packet.path import build_fullpaths
from lib.packet.scion import SCIONPacket, get_type, PathRequest, PathRecord,\
        PathInfo
from lib.packet.scion import PacketType as PT
from lib.topology import ElementType
from infrastructure.server import ServerBase
from infrastructure.path_server import update_dict
import sys
import threading
import logging

PATHS_NO = 5 #conf parameter?

class SCIONDaemon(ServerBase):
    """
    The SCION Daemon.
    """

    TIMEOUT = 7

    def __init__(self, addr, topo_file, config_file):
        ServerBase.__init__(self, addr, topo_file, config_file)
        #TODO replace by pathstore instance
        self.up_paths = []
        self.down_paths = {}
        self._waiting_targets = {}

    def request_paths(self, type, isd, ad):
        """
        Sends path request with certain type for (isd,ad).
        """
        info = PathInfo.from_values(type, isd, ad)
        path_request = PathRequest.from_values(self.addr, info)
        dst = self.topology.servers[ElementType.PATH_SERVER].addr
        self.send(path_request, dst)

    def get_paths(self, isd, ad):
        """
        Returns list of paths
        """
        if self.up_paths and (isd, ad) in self.down_paths:
            return build_fullpaths(self.up_paths, self.down_paths[(isd, ad)])
        else:
            event = threading.Event()
            self._waiting_targets[(isd, ad)] = event
            self.request_paths(PathInfo.BOTH_PATHS, isd, ad)
            self._waiting_targets[(isd, ad)].wait(SCIONDaemon.TIMEOUT)
            del self._waiting_targets[(isd, ad)]
            if self.up_paths and (isd, ad) in self.down_paths:
                return build_fullpaths(self.up_paths,
                    self.down_paths[(isd, ad)])
            else:
                return []

    def update_down_paths(self, isd_ad, pcbs):
        """
        Updates local storage of down paths.
        """
        update_dict(self.down_paths, isd_ad, pcbs)
        self.down_paths[isd_ad] = self.down_paths[isd_ad][:PATHS_NO]

    def handle_path_reply(self, packet):
        """
        Handles path reply from local path server.
        """
        path_reply = PathRecord(packet)
        for pcb in path_reply.pcbs:
            isd = pcb.get_isd()
            ad = pcb.get_last_ad()
            if self.topology.isd_id != isd or self.topology.ad_id != ad:
                update_dict(self.down_paths, (isd, ad), [pcb], PATHS_NO)
                logging.info("DownPath PATH added for (%d,%d)", isd, ad)
            else:
                self.up_paths.append(pcb)
                logging.info("UP PATH added")

        #wake up sleeping get_paths()
        if (isd, ad) in self._waiting_targets:
            self._waiting_targets[(isd, ad)].set()

    def handle_request(self, packet, sender, from_local_socket=True):
        """
        Main routine to handle incoming SCION packets.
        """
        spkt = SCIONPacket(packet)
        ptype = get_type(spkt)

        if ptype == PT.PATH_REP:
            self.handle_path_reply(packet)
        else:
            logging.warning("Type %d not supported.", ptype)

    def get_first_hop(self, spkt):
        """
        Returns first hop addr of down-path or end-host addr.
        """
        of = spkt.hdr.path.up_path_hops[0]
        return self.ifid2addr[of.ingress_if]

def main():
    logging.basicConfig(level=logging.DEBUG)
    if len(sys.argv) != 4:
        logging.error("run: %s IP topo_file conf_file", sys.argv[0])
        sys.exit()
    sd = SCIONDaemon(IPv4HostAddr(sys.argv[1]), sys.argv[2], sys.argv[3])
    threading.Thread(target=sd.run).start()
    path = sd.get_paths(11, 6)[0]
    dst = IPv4HostAddr("192.168.6.106")
    scion_pkt = SCIONPacket.from_values(sd.addr, dst, b"payload", path)
    hop = sd.get_first_hop(scion_pkt)
    sd.send(scion_pkt, hop)
    logging.info("Send packet to: %s", hop)

if __name__ == "__main__":
    main()
