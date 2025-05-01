import socket
import json
import yaml
import logging
import threading
import tkinter as tk
from tkinter import ttk
from queue import Queue
from datetime import datetime

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
        self.host = config['drone']['server_ip']
        self.port = config['drone']['server_port']

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

if __name__ == '__main__':
    app = ServerGUI()
    app.mainloop() 