import socket
import json
import yaml
import logging
import threading
import tkinter as tk
from tkinter import ttk
from queue import Queue
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
from collections import defaultdict, deque
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

class ServerGUI(tk.Tk):
    def __init__(self, config_path='config.yaml'):
        super().__init__()
        # Load configuration
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Server bind address
        self.host = config['server']['ip']
        self.port = config['server']['port']

        # Window setup
        self.title("Environmental Monitoring - Central Server")
        self.geometry("800x600")

        # Treeview to display incoming summaries including drone and sensor info
        columns = ('timestamp', 'drone_id', 'sensor_ids', 'avg_temp', 'avg_humidity', 'battery')
        self.tree = ttk.Treeview(self, columns=columns, show='headings')
        self.tree.heading('timestamp', text='Timestamp')
        self.tree.heading('drone_id', text='Drone ID')
        self.tree.heading('sensor_ids', text='Sensor IDs')
        self.tree.heading('avg_temp', text='Avg Temp (°C)')
        self.tree.heading('avg_humidity', text='Avg Humidity (%)')
        self.tree.heading('battery', text='Battery (%)')
        
        self.tree.column('timestamp', width=200)
        self.tree.column('drone_id', width=100, anchor=tk.CENTER)
        self.tree.column('sensor_ids', width=150, anchor=tk.CENTER)
        self.tree.column('avg_temp', width=120, anchor=tk.CENTER)
        self.tree.column('avg_humidity', width=120, anchor=tk.CENTER)
        self.tree.column('battery', width=100, anchor=tk.CENTER)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Anomalies text area
        ttk.Label(self, text="Anomalies:").pack(pady=(10, 0))
        self.anomaly_text = tk.Text(self, height=8)
        self.anomaly_text.pack(fill=tk.BOTH, padx=5, pady=5)
        self.anomaly_text.tag_config('anomaly', foreground='red')

        # Message queue for inter-thread communication
        self.msg_queue = Queue()

        # Start server listener thread
        threading.Thread(target=self.run_server, daemon=True).start()
        # Start periodic GUI update
        self.after(500, self.process_queue)

    def process_queue(self):
        # Process all messages in queue
        while not self.msg_queue.empty():
            msg = self.msg_queue.get()
            # Parse and format timestamp
            raw_ts = msg.get('timestamp', '')
            try:
                dt = datetime.strptime(raw_ts, '%Y-%m-%dT%H:%M:%SZ')
                ts = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                ts = raw_ts
            # Get drone and sensor info
            drone_id = msg.get('drone_id', '')
            sensor_ids = msg.get('sensor_ids', [])
            sensor_ids_str = ','.join(sensor_ids)
            avg_t = msg.get('average_temperature', 0)
            avg_h = msg.get('average_humidity', 0)
            bat = msg.get('battery_level', 0)
            # Insert summary into treeview
            self.tree.insert('', tk.END, values=(ts, drone_id, sensor_ids_str, f"{avg_t:.2f}", f"{avg_h:.2f}", f"{bat}%"))
            # Display anomalies
            for anomaly in msg.get('anomalies', []):
                text = f"[{anomaly['timestamp']}] {anomaly['sensor_id']} -> Temp: {anomaly['value']}°C\n"
                self.anomaly_text.insert(tk.END, text, 'anomaly')

        # Schedule next poll
        self.after(500, self.process_queue)

    def run_server(self):
        # Set up TCP server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)
        logging.info(f"Server listening on {self.host}:{self.port}")

        while True:
            client, addr = sock.accept()
            logging.info(f"Drone connected from {addr}")
            threading.Thread(
                target=self.handle_client,
                args=(client,),
                daemon=True
            ).start()

    def handle_client(self, client_sock):
        # Handle incoming data from drone
        buffer = b''
        with client_sock:
            while True:
                try:
                    data = client_sock.recv(4096)
                    if not data:
                        break
                    buffer += data
                    try:
                        msg = json.loads(buffer.decode('utf-8'))
                        self.msg_queue.put(msg)
                        buffer = b''
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except ConnectionResetError:
                    break
        logging.info("Drone disconnected")

class CentralServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Central Server Monitor")
        self.geometry("1200x800")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.queue = Queue()
        self.running = True
        self.drone_data = defaultdict(lambda: {
            'timestamps': deque(maxlen=50),
            'temperatures': deque(maxlen=50),
            'humidities': deque(maxlen=50),
            'battery': deque(maxlen=50)
        })
        self.anomalies = defaultdict(list)
        self.setup_gui()
        self.process_queue()
        self.update_plots()

    def setup_gui(self):
        # Create main frames
        left_frame = ttk.Frame(self)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        right_frame = ttk.Frame(self)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Create plots in left frame
        self.fig = Figure(figsize=(6, 8))
        self.temp_ax = self.fig.add_subplot(211)
        self.hum_ax = self.fig.add_subplot(212)
        self.canvas = FigureCanvasTkAgg(self.fig, master=left_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Initialize plots
        self.temp_lines = {}
        self.hum_lines = {}
        self.temp_ax.set_title('Temperature Over Time')
        self.hum_ax.set_title('Humidity Over Time')
        self.temp_ax.set_ylabel('°C')
        self.hum_ax.set_ylabel('%')
        self.temp_ax.legend()
        self.hum_ax.legend()
        self.fig.tight_layout()

        # Anomaly list in right frame
        anomaly_frame = ttk.LabelFrame(right_frame, text="Anomalies")
        anomaly_frame.pack(fill=tk.X, pady=5)
        self.anomaly_text = tk.Text(anomaly_frame, height=5)
        self.anomaly_text.pack(fill=tk.X)

        # Connected drones list in right frame
        drones_frame = ttk.LabelFrame(right_frame, text="Connected Drones")
        drones_frame.pack(fill=tk.X, pady=5)
        self.drones_text = tk.Text(drones_frame, height=5)
        self.drones_text.pack(fill=tk.X)

        # Battery levels in right frame
        battery_frame = ttk.LabelFrame(right_frame, text="Battery Levels")
        battery_frame.pack(fill=tk.X, pady=5)
        self.battery_bars = {}
        self.battery_frame = battery_frame

        # Treeview to display incoming summaries
        columns = ('timestamp', 'drone_id', 'sensor_ids', 'avg_temp', 'avg_humidity', 'battery')
        self.tree = ttk.Treeview(self, columns=columns, show='headings')
        self.tree.heading('timestamp', text='Timestamp')
        self.tree.heading('drone_id', text='Drone ID')
        self.tree.heading('sensor_ids', text='Sensor IDs')
        self.tree.heading('avg_temp', text='Avg Temp (°C)')
        self.tree.heading('avg_humidity', text='Avg Humidity (%)')
        self.tree.heading('battery', text='Battery (%)')
        self.tree.pack(fill=tk.BOTH, expand=True)

    def update_plots(self):
        # Clear existing lines
        for line in self.temp_lines.values():
            line.remove()
        for line in self.hum_lines.values():
            line.remove()
        self.temp_lines.clear()
        self.hum_lines.clear()

        # Plot data for each drone
        for drone_id, data in self.drone_data.items():
            if data['timestamps']:
                self.temp_lines[drone_id], = self.temp_ax.plot(
                    list(data['timestamps']), list(data['temperatures']),
                    label=f'Drone {drone_id}'
                )
                self.hum_lines[drone_id], = self.hum_ax.plot(
                    list(data['timestamps']), list(data['humidities']),
                    label=f'Drone {drone_id}'
                )

        # Update plot limits and legend
        self.temp_ax.relim()
        self.temp_ax.autoscale_view()
        self.hum_ax.relim()
        self.hum_ax.autoscale_view()
        self.temp_ax.legend()
        self.hum_ax.legend()
        self.canvas.draw()

        # Schedule next update
        self.after(1000, self.update_plots)

    def process_queue(self):
        while self.running:
            try:
                msg = self.queue.get(timeout=0.1)
                # Parse and format timestamp
                raw_ts = msg.get('timestamp', '')
                try:
                    dt = datetime.strptime(raw_ts, '%Y-%m-%dT%H:%M:%SZ')
                    ts = dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    ts = raw_ts
                # Get drone and sensor info
                drone_id = msg.get('drone_id', '')
                sensor_ids = msg.get('sensor_ids', [])
                sensor_ids_str = ','.join(sensor_ids)
                avg_t = msg.get('average_temperature', 0)
                avg_h = msg.get('average_humidity', 0)
                bat = msg.get('battery_level', 0)

                # Update drone data for plots
                self.drone_data[drone_id]['timestamps'].append(time.time())
                self.drone_data[drone_id]['temperatures'].append(avg_t)
                self.drone_data[drone_id]['humidities'].append(avg_h)
                self.drone_data[drone_id]['battery'].append(bat)

                # Update anomalies
                if 'anomalies' in msg:
                    self.anomalies[drone_id].extend(msg['anomalies'])

                # Update battery bars
                if drone_id not in self.battery_bars:
                    frame = ttk.Frame(self.battery_frame)
                    frame.pack(fill=tk.X, pady=2)
                    ttk.Label(frame, text=f"Drone {drone_id}:").pack(side=tk.LEFT)
                    bar = ttk.Progressbar(frame, length=200, mode='determinate', maximum=100)
                    bar.pack(side=tk.LEFT, padx=5)
                    self.battery_bars[drone_id] = bar
                self.battery_bars[drone_id]['value'] = bat

                # Update anomaly text
                self.anomaly_text.delete(1.0, tk.END)
                for d_id, anomalies in self.anomalies.items():
                    for anomaly in anomalies:
                        self.anomaly_text.insert(tk.END, f"Drone {d_id}: {anomaly}\n")

                # Update drones text
                self.drones_text.delete(1.0, tk.END)
                for d_id in self.drone_data.keys():
                    self.drones_text.insert(tk.END, f"Drone {d_id}\n")

                # Insert summary into treeview
                self.tree.insert('', tk.END, values=(ts, drone_id, sensor_ids_str, f"{avg_t:.2f}", f"{avg_h:.2f}", f"{bat}%"))
            except Empty:
                continue

if __name__ == '__main__':
    app = ServerGUI()
    app.mainloop() 