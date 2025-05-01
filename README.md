# Drone-Enabled Environmental Monitoring System

**Group 14:** Enes Coşkun, Oğuz Temelli, Melihtan Özkut  

---

## 1. Project Overview  
In this project, we simulate a simple environmental monitoring system comprising sensor nodes, a drone acting as an edge node, and a central server.  
- **Sensor Nodes** generate and send periodic environmental data (temperature and humidity) via TCP to the drone.  
- **Drone (Edge Node)** processes incoming data, detects anomalies, tracks its battery level, and forwards a summarized JSON message to the central server.  
- **Central Server** receives processed summaries and displays them on a GUI for real-time monitoring and logging. citeturn1file1

---

## 2. System Architecture  
```
Sensor Nodes (TCP Clients) ──► Drone (TCP Server / Client) ──► Central Server (TCP Server)
```
- **TCP** is used to guarantee reliable delivery.  
- **JSON** is the chosen data format for simplicity and cross-language compatibility. citeturn1file1

---

## 3. Module Descriptions  

| Component      | Purpose                                    | Inputs                         | Outputs                            | Core Logic                                 |
| -------------- | ------------------------------------------ | ------------------------------ | ---------------------------------- | ------------------------------------------ |
| **Sensor Node**| Generate & send environmental data         | Config (IP, port, interval)    | JSON sensor readings via TCP       | Data generation loop; reconnect logic      |
| **Drone**      | Process sensor data; forward summaries     | Sensor JSON + battery params   | JSON summary messages; GUI status  | Rolling averages; anomaly detection; battery management  |
| **Server**     | Visualize processed data & anomalies       | Drone JSON summaries           | GUI visuals; anomaly/event logs    | Data visualization; logging                | citeturn1file0

---

## 4. Data Format & Protocol  
- **Sensor message:**  
  ```json
  {
    "sensor_id": "sensor1",
    "temperature": 22.5,
    "humidity": 55,
    "timestamp": "2025-02-10T10:00:00Z"
  }
  ```
- **Drone summary message:**  
  ```json
  {
    "average_temperature": 21.7,
    "average_humidity": 53,
    "anomalies": [
      {"sensor_id":"sensor2","value":1000,"timestamp":"..."}
    ],
    "timestamp":"2025-02-10T10:00:05Z"
  }
  ``` citeturn1file1

---

## 5. Design Rationale  
- **TCP vs UDP:** Chose TCP for reliable delivery—no risk of lost packets.  
- **JSON Format:** Human-readable, language-agnostic, easy parsing.  
- **Edge Processing on Drone:** Reduces server load—anomalies caught and filtered before forwarding.  
- **Modular Architecture:** Each component can be developed, tested, and debugged independently. citeturn1file0

---

## 6. Potential Design Issues & Mitigations  

| Issue                     | Description                                  | Handling                                |
| ------------------------- | -------------------------------------------- | --------------------------------------- |
| Data Loss                 | Corrupted/incomplete transmissions           | Retransmit on failure; detailed logging |
| Sensor Disconnection      | Sensor nodes dropping off                    | Auto-reconnect logic; GUI reflects drop |
| Concurrent Connections    | Multiple sensors sending simultaneously      | Multithreading or `asyncio`             |
| Low Battery Mode          | Drone battery depletes during operation      | Return-to-base logic; queue or disconnect incoming data |
| GUI Responsiveness        | Blocking operations freeze UI               | Separate GUI threads or asynchronous I/O |

---

## 7. Test Scenarios  

1. **Normal Operation**  
   - ≥2 sensor nodes send data → drone aggregates → forwards to server → GUIs update correctly.

2. **Sensor Disconnection**  
   - Simulate sensor crash → drone logs event & GUI reflects missing data → sensor attempts reconnection.

3. **Low Battery Return to Base**  
   - Battery drops below threshold → drone logs “Returning to base” → handles incoming data per chosen strategy.

4. **Anomaly Detection**  
   - Force out-of-range sensor values (e.g., temperature=1000°C) → drone flags anomaly & GUI highlights it → server logs the anomaly.

---

## 8. Contributors  
- **Enes Coşkun**  
- **Oğuz Temelli**  
- **Melihtan Özkut**

---
