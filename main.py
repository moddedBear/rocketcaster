#!/usr/bin/env python3
import jetforce
import argparse

from rocketcaster import app

parser = argparse.ArgumentParser()
parser.add_argument('--hostname, -H', type=str,
                    help='the hostname of the server', dest='hostname', default=None)
parser.add_argument('--certfile, -c', type=str,
                    help='the path to the server\'s certfile', dest='certfile', default=None)
parser.add_argument('--keyfile, -k', type=str,
                    help='the path to the server\'s keyfile', dest='keyfile', default=None)
args = parser.parse_args()

server = jetforce.GeminiServer(app)
if args.hostname:
    server.hostname = args.hostname
if args.certfile:
    server.certfile = args.certfile
if args.keyfile:
    server.keyfile = args.keyfile
server.run()
