#!/usr/bin/env python3
import jetforce
import argparse

from rocketcaster import app, init_db

parser = argparse.ArgumentParser()
parser.add_argument('--hostname, -H', type=str,
                    help='the hostname of the server', dest='hostname', default=None)
parser.add_argument('--host', type=str,
                    help='the local socket to bind to', dest='host', default='0.0.0.0')
parser.add_argument('--certfile, -c', type=str,
                    help='the path to the server\'s certfile', dest='certfile', default=None)
parser.add_argument('--keyfile, -k', type=str,
                    help='the path to the server\'s keyfile', dest='keyfile', default=None)
parser.add_argument('--db', type=str, help='the path to the database',
                    dest='db_path', default='./db.sqlite')
args = parser.parse_args()

server = jetforce.GeminiServer(app)
if args.hostname:
    server.hostname = args.hostname
if args.certfile:
    server.certfile = args.certfile
if args.keyfile:
    server.keyfile = args.keyfile
server.host = args.host
init_db(args.db_path)
server.run()
