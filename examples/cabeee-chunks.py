# -*- Mode:python; c-file-style:"gnu"; indent-tabs-mode:nil -*- */
#
# Copyright (C) 2015-2021, The University of Memphis,
#                          Arizona Board of Regents,
#                          Regents of the University of California.
#
# This file is part of Mini-NDN.
# See AUTHORS.md for a complete list of Mini-NDN authors and contributors.
#
# Mini-NDN is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Mini-NDN is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Mini-NDN, e.g., in COPYING.md file.
# If not, see <http://www.gnu.org/licenses/>.

#from subprocess import PIPE
import subprocess

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.util import MiniNDNCLI, getPopen
from minindn.apps.nfd import Nfd
from minindn.helpers.nfdc import Nfdc
from minindn.helpers.ndn_routing_helper import NdnRoutingHelper
import argparse
from minindn.apps.nlsr import Nlsr
from minindn.helpers.ip_routing_helper import IPRoutingHelper
from minindn.helpers.merge_nfd_logs import MergeNFDLogs
from minindn.util import copyExistentFile

from time import sleep
from os import environ

USER_HOME = environ['HOME']
MININDN_DIR = USER_HOME + '/mini-ndn'

PREFIX = "/interCACHE"

BIN_DIR = MININDN_DIR + '/dl/ndn-cxx/build/examples'
TOPOLOGY_DIR = MININDN_DIR + '/topologies'

def printOutput(output):
    _out = output.decode("utf-8").split("\n")
    for _line in _out:
        info(_line + "\n")

def sendFile(node, prefix, file):
    """
    Publish a file using ndnputchunks
     :parma mininet.node.Host node: mininet node object
     :param string prefix: prefix to publish the chunks of the file
     :param string file: file to publish
    """
    info ("File published:", file)
    cmd = 'ndnputchunks {}/{} < {} > putchunks.log 2>&1 &'.format(prefix, "fname", file)
    #cmd = 'ndnputchunks -s 2 {}/{} < {} > putchunks.log 2>&1 &'.format(prefix, "fname", file) # set the max segment size to 2 bytes
    node.cmd(cmd)
    # Sleep for appropriate time based on the file size
    sleep(5)

def receiveFile(node, prefix, filename):
    """
    Fetch a file using ndncatchunks
     :parma mininet.node.Host node: mininet node object
     :param string prefix: producer's prefix under which the file the published
     :param string file: name given to the file that will be received
    """
    info ("Fething file: ", filename)
    cmd = 'ndncatchunks {}/{} > {} 2> catchunks.log &'.format(prefix, "fname", filename)
    node.cmd(cmd)

def run():
    Minindn.cleanUp()
    Minindn.verifyDependencies()

    MergeNFDLogs.deleteAllLogs()




    """
    There are multiple ways of setting up routes in Mini-NDN
    refer: https://minindn.memphis.edu/experiment.html#routing-options
    """
    routeOption = 2


    if routeOption == 0:
        # OPTION 0
        # set up routes manually. The important bit to note here is the use of the Nfdc command

        ndn = Minindn(topoFile='topologies/cabeee-3node.conf')
        #ndn = Minindn(topoFile='topologies/cabeee-3node-slow.conf')
        ndn.start()

        info('Setting up routes manually in NFD\n')
        #links = {"sensor":["rtr1"], "rtr1":["rtr2"], "rtr2":["rtr3"], "rtr3":["orch"], "orch":["user"]} # routes are directional! This is the wrong direction.
        links = {"user":["orch"], "orch":["rtr3"], "rtr3":["rtr2"], "rtr2":["rtr1"], "rtr1":["sensor"]}
        for first in links:
            for second in links[first]:
                host1 = ndn.net[first]
                host2 = ndn.net[second]
                interface = host2.connectionsTo(host1)[0][0]
                interface_ip = interface.IP()
                Nfdc.createFace(host1, interface_ip)
                Nfdc.registerRoute(host1, PREFIX, interface_ip, cost=0)

        sleep(1)

    if routeOption == 1:
        # OPTION 1
        # set up routes using Link State Routing (NLSR).

        ndn = Minindn(topoFile='topologies/cabeee-3node.conf')
        #ndn = Minindn(topoFile='topologies/cabeee-3node-slow.conf')
        ndn.start()

        info('Adding IP routes to NFD\n')
        #info('Starting NFD on nodes\n')
        nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
        info('Starting NLSR on nodes\n')
        nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)

        sleep(90)

    if routeOption == 2:
        # OPTION 2
        # use static routing as used in static_routing_experiment.py
    
        # the following parser came from static_routing_experiment.py
        parser = argparse.ArgumentParser()
        parser.add_argument('--face-type', dest='faceType', default='udp', choices=['udp', 'tcp'])
        parser.add_argument('--routing', dest='routingType', default='link-state',
                            choices=['link-state', 'hr', 'dry'],
                            help='''Choose routing type, dry = link-state is used
                                    but hr is calculated for comparision.''')

        ndn = Minindn(parser=parser, topoFile='topologies/cabeee-3node.conf')
        #ndn = Minindn(parser=parser, topoFile='topologies/cabeee-3node-slow.conf')
        #ndn = Minindn(topoFile='topologies/cabeee-default-topology.conf')
        ndn.start()

        # configure and start nfd on each node
        info("Configuring NFD\n")
        nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")

        info('Adding static routes to NFD\n')
        grh = NdnRoutingHelper(ndn.net, ndn.args.faceType, ndn.args.routingType)
        # For all host, pass ndn.net.hosts or a list, [ndn.net['a'], ..] or [ndn.net.hosts[0],.]
        grh.addOrigin([ndn.net['sensor']], [PREFIX])
        grh.calculateNPossibleRoutes()
        #PREFIX is advertised from node "sensor", it should be reachable from all other nodes.
        routesFromSensor = ndn.net['sensor'].cmd("nfdc route | grep -v '/localhost/nfd'")
        if '/ndn/rtr1-site/rtr1' not in routesFromSensor or \
           '/ndn/rtr2-site/rtr2' not in routesFromSensor or \
           '/ndn/rtr3-site/rtr3' not in routesFromSensor or \
           '/ndn/orch-site/orch' not in routesFromSensor or \
           '/ndn/user-site/user' not in routesFromSensor:
            info("Route addition failed\n")
        routesToPrefix = ndn.net['rtr1'].cmd("nfdc fib | grep '/interCACHE'")
        if '/interCACHE' not in routesToPrefix:
            info("Missing route to advertised prefix, Route addition failed\n")
            ndn.net.stop()
            sys.exit(1)
        routesToPrefix = ndn.net['rtr2'].cmd("nfdc fib | grep '/interCACHE'")
        if '/interCACHE' not in routesToPrefix:
            info("Missing route to advertised prefix, Route addition failed\n")
            ndn.net.stop()
            sys.exit(1)
        routesToPrefix = ndn.net['rtr3'].cmd("nfdc fib | grep '/interCACHE'")
        if '/interCACHE' not in routesToPrefix:
            info("Missing route to advertised prefix, Route addition failed\n")
            ndn.net.stop()
            sys.exit(1)
        routesToPrefix = ndn.net['orch'].cmd("nfdc fib | grep '/interCACHE'")
        if '/interCACHE' not in routesToPrefix:
            info("Missing route to advertised prefix, Route addition failed\n")
            ndn.net.stop()
            sys.exit(1)
        info('Route addition to NFD completed\n')

        sleep(1)

    if routeOption == 3:
        # OPTION 3
        # use IP routing as used in ip_rounting_experiment.py

        ndn = Minindn(topoFile='topologies/cabeee-3node.conf')
        #ndn = Minindn(topoFile='topologies/cabeee-3node-slow.conf')
        #ndn = Minindn(topoFile='topologies/cabeee-default-topology.conf')
        ndn.start()

        # NOTE: this method is also used in traffic_generator.py, pcap_logging_experiment.py, and consumer-producer.py
        info('Adding IP routes to NFD\n')
        #info('Starting NFD on nodes\n')
        nfds = AppManager(ndn, ndn.net.hosts, Nfd, logLevel="DEBUG")
        info('Starting NLSR on nodes\n')
        nlsrs = AppManager(ndn, ndn.net.hosts, Nlsr)

        # Calculate all routes for IP routing
        IPRoutingHelper.calcAllRoutes(ndn.net)
        info("IP routes configured\n")

        sleep(90)





    # next try doing a simple example as in examples/chunks.py
    #      this might be the closest to what I did in ndnSIM, as far as generating a single interest at a time
    #      and adding the application-parameters. The data in response can be sent via a file. Perhaps there is a better way (without having to create a file?)



    # Create a test file to publish
    testFile = "/tmp/cabeee-test-chunks-to-transmit"
    cmd = 'echo "cabeee - demonstrate file transfer using catchunks and putchunks" > {}'.format(testFile)
    subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).communicate()


    producer  = ndn.net['sensor']
    producerPrefix = PREFIX # prefix under which the file will be published
    consumer = ndn.net['user']

    # Advertise the producer prefix to the network
    producer.cmd('nlsrc advertise {}'.format(producerPrefix))
    sleep (5) # sleep for routing convergence.

    sendFile(producer, producerPrefix, testFile)
    receiveFile(consumer, producerPrefix, "cabeee-test-chunks-received")





    '''
    producer = ndn.net['sensor']
    consumer = ndn.net['user']


    producer.cmd('nlsrc advertise {}'.format(PREFIX))
    sleep(5) # sleep for routing convergence

    # Make sure that basic consumer/producer example are compiled and installed in the system
    info('Starting consumer and producer application\n')
    producer.cmd("echo 'HELLO WORLD' | ndnpoke {} &> producer.log &".format(PREFIX))
    consumer.cmd("ndnpeek -p {} &> consumer.log &".format(PREFIX))
    '''






    info("\nExperiment Completed!\n")
    MiniNDNCLI(ndn.net)
    ndn.stop()

    # concatenate every node's log/nfd.log file to a single one. Keep timestamp, add node name. Sort by timestamp!
    MergeNFDLogs.mergeAllLogs()

if __name__ == '__main__':
    setLogLevel("info")
    #setLogLevel("debug")
    run()
