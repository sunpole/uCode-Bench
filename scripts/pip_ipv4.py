"""Use IPv4 for this pip invocation on a workstation with broken IPv6 routing."""
import runpy
import socket
import sys
import pip._vendor.urllib3.util.connection

pip._vendor.urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
sys.argv[0] = "pip"
runpy.run_module("pip", run_name="__main__")
