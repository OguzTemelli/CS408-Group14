import socket
import json
import yaml
import logging
import threading
import time
import math
from datetime import datetime
from collections import deque
import argparse

# Parse command-line arguments
parser = argparse.ArgumentParser(description='Drone edge node')
parser.add_argument('--config', '-c', default='config.yaml', help='Path to config YAML')
parser.add_argument('--listen_port', type=int, help='Override sensor listener port')
parser.add_argument('--server_ip', help='Override central server IP')
parser.add_argument('--server_port', type=int, help='Override central server port')
parser.add_argument('--battery_threshold', type=int, help='Override battery threshold')
parser.add_argument('--battery_initial', type=int, help='Initial battery level')
parser.add_argument('--id', help='Override drone id')
parser.add_argument('--gui', action='store_true', help='Launch drone GUI')
args = parser.parse_args()

# Load configuration
with open(args.config, 'r') as f:
    cfg = yaml.safe_load(f)

# Apply overrides
listen_port = args.listen_port or cfg['drone']['listen_port']
server_ip = args.server_ip or cfg['drone']['server_ip']
server_port = args.server_port or cfg['drone']['server_port']
battery_threshold = args.battery_threshold or cfg['drone']['battery_threshold']
battery_level = args.battery_initial or cfg['drone'].get('battery_initial', 100)
drone_id = args.id or cfg['drone'].get('id', 'drone1')

# Setup logging
logger = logging.getLogger('drone')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
fh = logging.FileHandler('drone.log')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(ch)
logger.addHandler(fh)

# Data storage
temp_readings = deque(maxlen=10)
hum_readings = deque(maxlen=10)
anomalies = []
sensor_ids = set()
returning_to_base = False

# Battery simulation
def update_battery():
    global battery_level, returning_to_base
    while battery_level > 0:
        time.sleep(60)  # simulate 1% drain per minute
        battery_level -= 1
        logger.info(f"Battery level: {battery_level}%")
        if battery_level <= battery_threshold and not returning_to_base:
            returning_to_base = True
            logger.warning("Battery low - Returning to base!")
            # stub: could disconnect sensors or queue data

# Anomaly detection based on rolling stddev

def detect_anomaly(value, readings):
    if len(readings) < readings.maxlen:
        return False
    mean = sum(readings) / len(readings)
    var = sum((x - mean) ** 2 for x in readings) / len(readings)
    std = math.sqrt(var)
    if abs(value - mean) > 2 * std:
        return True
    return False

# Handle sensor connections

def handle_sensor_connection(client_sock, addr):
    logger.info(f"Sensor connected from {addr}")
    buffer = b''
    with client_sock:
        while True:
            try:
                chunk = client_sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                try:
                    reading = json.loads(buffer.decode('utf-8'))
                    buffer = b''
                    temp = reading.get('temperature')
                    hum = reading.get('humidity')
                    ts = reading.get('timestamp')
                    sensor_ids.add(reading.get('sensor_id', ''))
                    temp_readings.append(temp)
                    hum_readings.append(hum)
                    logger.debug(f"Received {reading['sensor_id']} -> temp={temp}, hum={hum}")
                    if detect_anomaly(temp, temp_readings):
                        anomalies.append({'sensor_id': reading['sensor_id'], 'value': temp, 'timestamp': ts})
                        logger.warning(f"Anomaly detected: {reading}")
                except json.JSONDecodeError:
                    continue
            except ConnectionResetError:
                break
            except Exception as e:
                logger.error(f"Error handling sensor: {e}")
                break
    logger.info(f"Sensor disconnected from {addr}")

# Forward summary to central server

def send_summary():
    global anomalies, sensor_ids
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server_ip, server_port))
            while True:
                if temp_readings:
                    avg_temp = sum(temp_readings) / len(temp_readings)
                    avg_hum = sum(hum_readings) / len(hum_readings)
                else:
                    avg_temp = avg_hum = 0
                summary = {
                    'drone_id': drone_id,
                    'sensor_ids': list(sensor_ids),
                    'average_temperature': round(avg_temp, 2),
                    'average_humidity': round(avg_hum, 2),
                    'anomalies': anomalies,
                    'battery_level': battery_level,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
                sock.sendall(json.dumps(summary).encode('utf-8'))
                logger.info(f"Sent summary: {summary}")
                anomalies = []
                sensor_ids.clear()
                time.sleep(5)
        except Exception as e:
            logger.warning(f"Error sending to server: {e}" )
            time.sleep(5)

# Main drone logic

def main():
    # Start battery thread
    threading.Thread(target=update_battery, daemon=True).start()
    # Start summary thread
    threading.Thread(target=send_summary, daemon=True).start()
    # Start sensor server
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as serv:
        serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serv.bind(('0.0.0.0', listen_port))
        serv.listen(5)
        logger.info(f"Drone listening on port {listen_port}")
        while True:
            client_sock, addr = serv.accept()
            threading.Thread(target=handle_sensor_connection, args=(client_sock, addr), daemon=True).start()

if __name__ == '__main__':
    if args.gui:
        import tkinter as tk
        from tkinter import ttk
        from logging import Handler

        # Custom logging handler that writes to Tkinter Text
        class TextHandler(Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
            def emit(self, record):
                msg = self.format(record)
                def append():
                    self.text_widget.insert(tk.END, msg + '\n')
                    self.text_widget.see(tk.END)
                self.text_widget.after(0, append)

        # Start main drone logic in background
        threading.Thread(target=main, daemon=True).start()

        # Build GUI
        root = tk.Tk()
        root.title(f"Drone Monitor - {drone_id}")
        root.geometry("600x400")

        # Log panel
        log_text = tk.Text(root, height=15)
        log_text.pack(fill=tk.BOTH, expand=True)
        th = TextHandler(log_text)
        th.setLevel(logging.DEBUG)
        th.setFormatter(formatter)
        logger.addHandler(th)

        # Battery level progress bar
        ttk.Label(root, text="Battery Level:").pack(pady=(5, 0))
        batt_bar = ttk.Progressbar(root, length=200, mode='determinate', maximum=100)
        batt_bar.pack(pady=(0, 10))
        # Update battery UI periodically
        def update_battery_ui():
            batt_bar['value'] = battery_level
            root.after(1000, update_battery_ui)
        root.after(1000, update_battery_ui)

        root.mainloop()
    else:
        main() 