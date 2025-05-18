import subprocess
import yaml
import time
import sys
import os

with open('config.yaml', 'r') as f:
    cfg = yaml.safe_load(f)

processes = []

# Start server
server_ip = cfg['server']['ip']
server_port = cfg['server']['port']
print(f"Starting server on {server_ip}:{server_port}")
proc = subprocess.Popen([sys.executable, 'server.py'])
processes.append(proc)
time.sleep(1)

# Start drones
for drone in cfg['drones']:
    args = [sys.executable, 'drone.py', '--id', drone['id'], '--listen_port', str(drone['listen_port']), '--battery_threshold', str(drone['battery_threshold'])]
    if drone.get('gui', False):
        args.append('--gui')
    print(f"Starting drone {drone['id']} on port {drone['listen_port']}")
    proc = subprocess.Popen(args)
    processes.append(proc)
    time.sleep(1)

# Start sensors
for sensor in cfg['sensors']:
    args = [sys.executable, 'sensor.py', '--id', sensor['id'], '--drone_ip', sensor['drone_ip'], '--drone_port', str(sensor['drone_port'])]
    print(f"Starting sensor {sensor['id']} for drone at {sensor['drone_ip']}:{sensor['drone_port']}")
    proc = subprocess.Popen(args)
    processes.append(proc)
    time.sleep(1)

print("All components started. Press Ctrl+C to stop.")
try:
    for p in processes:
        p.wait()
except KeyboardInterrupt:
    print("Shutting down...")
    for p in processes:
        p.terminate()
    sys.exit(0) 