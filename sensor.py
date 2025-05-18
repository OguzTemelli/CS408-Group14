import argparse
import socket
import json
import yaml
import logging
import time
import random
from datetime import datetime

# Parse command-line arguments
parser = argparse.ArgumentParser(description='Sensor node')
parser.add_argument('--config', '-c', default='config.yaml', help='Path to config YAML')
parser.add_argument('--id', help='Override sensor ID')
parser.add_argument('--drone_ip', help='Override drone IP')
parser.add_argument('--drone_port', type=int, help='Override drone port')
parser.add_argument('--interval', type=float, help='Override send interval')
args = parser.parse_args()

# Load configuration
with open(args.config, 'r') as f:
    cfg = yaml.safe_load(f)

# Find this sensor's config from the sensors list
sensor_id = args.id
sensor_cfg = next(s for s in cfg['sensors'] if s['id'] == sensor_id)

# Apply settings, allowing overrides
interval = args.interval or 5  # veya config'e eklenmişse sensor_cfg['interval']
drone_ip = args.drone_ip or sensor_cfg['drone_ip']
drone_port = args.drone_port or sensor_cfg['drone_port']
sensor_id = args.id or sensor_cfg.get('id', 'sensor1')

# Configure logging
logger = logging.getLogger('sensor')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Console handler
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
# File handler
fh = logging.FileHandler('sensor.log')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)

logger.addHandler(ch)
logger.addHandler(fh)

def connect_to_drone():
    """Establish TCP connection to the drone with retry logic."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((drone_ip, drone_port))
            logger.info(f"Connected to drone at {drone_ip}:{drone_port}")
            return sock
        except Exception as e:
            logger.warning(f"Connection failed: {e}, retrying in 5 seconds...")
            time.sleep(5)

def generate_reading():
    """Generate a random sensor reading."""
    return {
        'sensor_id': sensor_id,
        'temperature': round(random.uniform(20.0, 30.0), 2),
        'humidity': round(random.uniform(30.0, 70.0), 2),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }

def main():
    sock = connect_to_drone()
    while True:
        reading = generate_reading()
        try:
            data = json.dumps(reading).encode('utf-8')
            sock.sendall(data)
            logger.debug(f"Sent reading: {reading}")
            time.sleep(interval)
        except Exception as e:
            logger.error(f"Error sending data: {e}")
            sock.close()
            sock = connect_to_drone()

if __name__ == '__main__':
    main() 