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
import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
from logging import Handler

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

# Find this drone's config from the drones list
drone_id = args.id
drone_cfg = next(d for d in cfg['drones'] if d['id'] == drone_id)
listen_port = args.listen_port or drone_cfg['listen_port']
battery_threshold = args.battery_threshold or drone_cfg['battery_threshold']
battery_level = args.battery_initial or drone_cfg.get('battery_initial', 100)
server_ip = args.server_ip or cfg['server']['ip']
server_port = args.server_port or cfg['server']['port']

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
anomalies_lock = threading.Lock()  # Thread-safe anomaly list
sensor_ids = set()
returning_to_base = False
running = True
status = 'Normal'  # Drone status for GUI
sensor_server = None  # Global for sensor server socket
active_sensor_sockets = []  # Aktif sensör bağlantıları
summary_thread = None
sensor_server_thread = None
anomaly_history = []
thread_lock = threading.Lock()  # Thread-safe flag update

# Battery simulation
def update_battery():
    global battery_level, returning_to_base, running, status, sensor_server, summary_thread, sensor_server_thread
    while True:
        with thread_lock:
            if not returning_to_base:
                if battery_level > 0:
                    time.sleep(60)  # simulate 1% drain per minute
                    battery_level -= 1
                    logger.info(f"Battery level: {battery_level}%")
                    if battery_level <= 10 and not returning_to_base:
                        returning_to_base = True
                        status = 'Returning to base'
                        logger.warning("Battery critically low (<=10%) - Returning to base! Closing sensor connections.")
                        # Close sensor server to stop accepting new sensors
                        if sensor_server:
                            try:
                                sensor_server.close()
                                logger.info("Sensor server closed. No longer accepting sensor connections.")
                            except Exception as e:
                                logger.error(f"Error closing sensor server: {e}")
                        # Close all active sensor sockets
                        for s in list(active_sensor_sockets):
                            try:
                                s.close()
                            except Exception:
                                pass
                        active_sensor_sockets.clear()
                        logger.info("All active sensor connections closed.")
                        running = False
                else:
                    returning_to_base = True
                    status = 'Returning to base'
                    logger.warning("Battery depleted. Returning to base!")
            else:
                logger.info("Drone is returning to base. Waiting 30 seconds...")
                status = 'Returning to base'
                time.sleep(30)
                status = 'Charging'
                logger.info("Drone is charging...")
                time.sleep(5)  # Simulate charging time
                battery_level = 100
                returning_to_base = False
                running = True
                status = 'Normal'
                logger.info("Drone is back in operation with full battery. Reopening sensor server.")
                # Reopen sensor server and restart summary thread (thread-safe)
                if sensor_server_thread is None or not sensor_server_thread.is_alive():
                    sensor_server_thread = threading.Thread(target=start_sensor_server, daemon=True)
                    sensor_server_thread.start()
                if summary_thread is None or not summary_thread.is_alive():
                    summary_thread = threading.Thread(target=send_summary, daemon=True)
                    summary_thread.start()

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
    active_sensor_sockets.append(client_sock)
    with client_sock:
        while not returning_to_base:
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
                        with anomalies_lock:
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
    if client_sock in active_sensor_sockets:
        active_sensor_sockets.remove(client_sock)

# Forward summary to central server

def send_summary():
    global anomalies, sensor_ids, running, anomaly_history
    while running and not returning_to_base:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server_ip, server_port))
            while running and not returning_to_base:
                if temp_readings:
                    avg_temp = sum(temp_readings) / len(temp_readings)
                    avg_hum = sum(hum_readings) / len(hum_readings)
                else:
                    avg_temp = avg_hum = 0
                with anomalies_lock:
                    anomalies_to_send = list(anomalies)
                    anomaly_history.extend(anomalies)
                    anomalies.clear()
                summary = {
                    'drone_id': drone_id,
                    'sensor_ids': list(sensor_ids),
                    'average_temperature': round(avg_temp, 2),
                    'average_humidity': round(avg_hum, 2),
                    'anomalies': anomalies_to_send,
                    'battery_level': battery_level,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
                sock.sendall(json.dumps(summary).encode('utf-8'))
                logger.info(f"Sent summary: {summary}")
                sensor_ids.clear()
                time.sleep(5)
        except Exception as e:
            logger.warning(f"Error sending to server: {e}" )
            time.sleep(5)

def start_sensor_server():
    global sensor_server
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as serv:
        sensor_server = serv
        serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serv.bind(('0.0.0.0', listen_port))
        serv.listen(5)
        logger.info(f"Drone listening on port {listen_port}")
        while not returning_to_base:
            try:
                client_sock, addr = serv.accept()
                threading.Thread(target=handle_sensor_connection, args=(client_sock, addr), daemon=True).start()
            except OSError:
                break  # Socket closed

# Main drone logic

def main():
    global summary_thread, sensor_server_thread
    # Start battery thread
    threading.Thread(target=update_battery, daemon=True).start()
    # Start summary thread
    summary_thread = threading.Thread(target=send_summary, daemon=True)
    summary_thread.start()
    # Start sensor server
    sensor_server_thread = threading.Thread(target=start_sensor_server, daemon=True)
    sensor_server_thread.start()

if __name__ == '__main__':
    if args.gui:
        import tkinter as tk
        from tkinter import ttk
        from logging import Handler
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        import numpy as np
        from collections import deque
        import time

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

        # Data storage for plots
        plot_data = {
            'timestamps': deque(maxlen=50),
            'temperatures': deque(maxlen=50),
            'humidities': deque(maxlen=50)
        }

        # Start main drone logic in background
        threading.Thread(target=main, daemon=True).start()

        # Build GUI
        root = tk.Tk()
        root.title(f"Drone Monitor - {drone_id}")
        root.geometry("1200x800")

        # Create main frames
        left_frame = ttk.Frame(root)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        right_frame = ttk.Frame(root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Log panel in right frame
        log_text = tk.Text(right_frame, height=15)
        log_text.pack(fill=tk.BOTH, expand=True)
        th = TextHandler(log_text)
        th.setLevel(logging.DEBUG)
        th.setFormatter(formatter)
        logger.addHandler(th)

        # Create plots in left frame
        fig = Figure(figsize=(6, 8))
        temp_ax = fig.add_subplot(211)
        hum_ax = fig.add_subplot(212)
        canvas = FigureCanvasTkAgg(fig, master=left_frame)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Initialize plots
        temp_line, = temp_ax.plot([], [], 'b-', label='Temperature')
        hum_line, = hum_ax.plot([], [], 'g-', label='Humidity')
        temp_ax.set_title('Temperature Over Time')
        hum_ax.set_title('Humidity Over Time')
        temp_ax.set_ylabel('°C')
        hum_ax.set_ylabel('%')
        temp_ax.legend()
        hum_ax.legend()
        fig.tight_layout()

        # Anomaly list in right frame
        anomaly_frame = ttk.LabelFrame(right_frame, text="Anomalies")
        anomaly_frame.pack(fill=tk.X, pady=5)
        anomaly_text = tk.Text(anomaly_frame, height=5)
        anomaly_text.pack(fill=tk.X)

        # Connected sensors list in right frame
        sensors_frame = ttk.LabelFrame(right_frame, text="Connected Sensors")
        sensors_frame.pack(fill=tk.X, pady=5)
        sensors_text = tk.Text(sensors_frame, height=5)
        sensors_text.pack(fill=tk.X)

        # Battery control in right frame
        battery_frame = ttk.LabelFrame(right_frame, text="Battery Control")
        battery_frame.pack(fill=tk.X, pady=5)

        # Battery level progress bar
        ttk.Label(battery_frame, text="Battery Level:").pack(pady=(5, 0))
        batt_bar = ttk.Progressbar(battery_frame, length=200, mode='determinate', maximum=100)
        batt_bar.pack(pady=(0, 5))

        # Battery control buttons
        def decrease_battery():
            global battery_level
            battery_level = max(0, battery_level - 10)
            batt_bar['value'] = battery_level

        def increase_battery():
            global battery_level
            battery_level = min(100, battery_level + 10)
            batt_bar['value'] = battery_level

        button_frame = ttk.Frame(battery_frame)
        button_frame.pack(pady=5)
        ttk.Button(button_frame, text="-10%", command=decrease_battery).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="+10%", command=increase_battery).pack(side=tk.LEFT, padx=5)

        # Update battery UI periodically
        def update_battery_ui():
            batt_bar['value'] = battery_level
            root.after(1000, update_battery_ui)
        root.after(1000, update_battery_ui)

        # Update plots periodically
        def update_plots():
            if temp_readings and hum_readings:
                plot_data['timestamps'].append(time.time())
                plot_data['temperatures'].append(sum(temp_readings) / len(temp_readings))
                plot_data['humidities'].append(sum(hum_readings) / len(hum_readings))

                temp_line.set_data(list(plot_data['timestamps']), list(plot_data['temperatures']))
                hum_line.set_data(list(plot_data['timestamps']), list(plot_data['humidities']))

                temp_ax.relim()
                temp_ax.autoscale_view()
                hum_ax.relim()
                hum_ax.autoscale_view()

                canvas.draw()
            root.after(1000, update_plots)
        root.after(1000, update_plots)

        # Update anomaly list
        def update_anomaly_list():
            anomaly_text.delete(1.0, tk.END)
            with anomalies_lock:
                for anomaly in anomaly_history + anomalies:
                    anomaly_text.insert(tk.END, f"{anomaly}\n")
            root.after(1000, update_anomaly_list)
        root.after(1000, update_anomaly_list)

        # Update connected sensors list
        def update_sensors_list():
            sensors_text.delete(1.0, tk.END)
            for sensor_id in sensor_ids:
                sensors_text.insert(tk.END, f"{sensor_id}\n")
            root.after(1000, update_sensors_list)
        root.after(1000, update_sensors_list)

        # Status label in right frame
        status_frame = ttk.LabelFrame(right_frame, text="Drone Status")
        status_frame.pack(fill=tk.X, pady=5)
        status_var = tk.StringVar(value=status)
        status_label = ttk.Label(status_frame, textvariable=status_var, font=("Arial", 14, "bold"))
        status_label.pack(pady=5)

        # Update status periodically
        def update_status():
            status_var.set(status)
            root.after(1000, update_status)
        root.after(1000, update_status)

        root.mainloop()
    else:
        main() 