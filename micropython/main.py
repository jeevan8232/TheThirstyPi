import network
import socket
import time
import json
import os
import ntptime
from machine import Pin, ADC
import dht

# ==========================================
# 1. CONFIGURATION
# ==========================================
WIFI_SSID = "<WIFI-SSID>"
WIFI_PASSWORD = "<WIFI-PASSWORD>"

AUTO_WATER_THRESHOLD = 30.0
SOIL_DRY = 65535
SOIL_WET = 20000 
PUMP_RUN_DURATION = 10

LOG_FILE = "datalog.csv"
MAX_FILE_SIZE = 1000000  
NORMAL_LOG_INTERVAL = 900  
ACTIVE_LOG_INTERVAL = 1    
TIMEZONE_OFFSET = 19800    

# ==========================================
# 2. HARDWARE SETUP
# ==========================================
dht_sensor = dht.DHT11(Pin(14))
adc_voltage = ADC(Pin(28))
adc_soil = ADC(Pin(27))

pump_ena = Pin(10, Pin.OUT, value=0) 
pump_1a  = Pin(8, Pin.OUT, value=0)  
pump_1b  = Pin(9, Pin.OUT, value=0)  

last_valid_temp = 0
last_valid_hum = 0
last_valid_rf = 0
last_dht_read_time = 0

# ==========================================
# 3. CORE FUNCTIONS & GLOBALS
# ==========================================
def control_pump(turn_on):
    if turn_on:
        pump_1a.value(1)
        pump_1b.value(0)
        pump_ena.value(1)
    else:
        pump_ena.value(0)
        pump_1a.value(0)
        pump_1b.value(0)

def calc_heat_index(t, h):
    if t < 20: return t
    hi = -8.78469475556 + 1.61139411*t + 2.33854883889*h - 0.14611605*t*h - \
         0.012308094*(t**2) - 0.01642482778*(h**2) + 0.002211732*(t**2)*h + \
         0.00072546*t*(h**2) - 0.000003582*(t**2)*(h**2)
    return round(hi, 2)

def get_readings():
    global last_valid_temp, last_valid_hum, last_valid_rf, last_dht_read_time
    current_time = time.time()
    
    if (current_time - last_dht_read_time) >= 2.5:
        try:
            dht_sensor.measure()
            last_valid_temp = dht_sensor.temperature()
            last_valid_hum = dht_sensor.humidity()
            last_valid_rf = calc_heat_index(last_valid_temp, last_valid_hum)
        except Exception:
            pass 
        last_dht_read_time = current_time
    
    raw_soil = adc_soil.read_u16()
    moisture = max(0, min(100, ((SOIL_DRY - raw_soil) / (SOIL_DRY - SOIL_WET)) * 100))
    volts = round((adc_voltage.read_u16() * (3.3/65535)) * 4.712, 2)
    
    return {
        "temp": last_valid_temp, "hum": last_valid_hum, "real_feel": last_valid_rf, 
        "soil": round(moisture, 1), "volts": volts, "pump": bool(pump_ena.value())
    }

def log_to_csv(data):
    file_exists = False
    try:
        file_size = os.stat(LOG_FILE)[6]
        file_exists = True
    except OSError:
        file_size = 0

    mode = 'w' if file_size > MAX_FILE_SIZE else 'a'
    try:
        with open(LOG_FILE, mode) as f:
            if mode == 'w' or not file_exists:
                f.write("Timestamp,Temp(C),RealFeel(C),Humidity(%),Soil(%),Volts(V),PumpOn,AutoMode,IgnoreMoist\n")
            
            t = time.localtime(time.time() + TIMEZONE_OFFSET)
            timestamp = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
            log_line = f"{timestamp},{data['temp']},{data['real_feel']},{data['hum']},{data['soil']},{data['volts']},{data['pump']},{data['auto_mode']},{data['ignore_moisture']}\n"
            
            f.write(log_line)
            log_type = "[1s ACTIVE]" if data['pump'] else "[15m ROUTINE]"
            print(f"DEBUG LOG {log_type}: {log_line.strip()}")
    except Exception as e:
        print("Logging Error:", e)

# HTML Helper Function
def make_opt(val, text, current_val):
    sel = "selected" if str(val) == str(current_val) else ""
    return f'<option value="{val}" {sel}>{text}</option>'

# ==========================================
# 4. NETWORK & TIME SETUP
# ==========================================
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASSWORD)
print("Connecting to Wi-Fi...")
while not wlan.isconnected(): 
    time.sleep(1)
print("Connected! IP:", wlan.ifconfig()[0])

try:
    print("Syncing time via NTP...")
    ntptime.settime()
except Exception as e:
    print("NTP Sync Failed:", e)

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(5)
s.setblocking(False)

# ==========================================
# 5. MAIN EXECUTION & STATE VARIABLES
# ==========================================
last_water_time = 0
last_log_time = 0
pump_stop_time = 0

# --- NEW SETTINGS VARIABLES ---
auto_mode_enabled = True  
water_interval = 86400    # Default: 24 Hours (in seconds)
ignore_moisture = False   # Default: Smart Mode (Check soil first)

print("\n=== SYSTEM ACTIVE ===")
print("Press Ctrl+C to safely exit and turn off the pump.")

try:
    while True:
        current_time = time.time()
        data = get_readings()
        data["auto_mode"] = auto_mode_enabled 
        data["ignore_moisture"] = ignore_moisture
        data["interval"] = water_interval

        # --- NON-BLOCKING PUMP SHUTOFF ---
        if data['pump'] and current_time >= pump_stop_time:
            control_pump(False)
            data['pump'] = False
            print("\n>>> PUMP STOPPED (Timer Finished)")
            last_water_time = current_time 

        # --- DYNAMIC LOGGING LOGIC ---
        current_log_interval = ACTIVE_LOG_INTERVAL if data['pump'] else NORMAL_LOG_INTERVAL
        if (current_time - last_log_time) >= current_log_interval:
            log_to_csv(data)
            last_log_time = current_time

        # --- SMART SCHEDULE & AUTO-IRRIGATE TRIGGER ---
        time_since_last = current_time - last_water_time
        interval_met = time_since_last >= water_interval

        if auto_mode_enabled and not data['pump'] and interval_met:
            if ignore_moisture:
                # Timer Mode: Ignore the soil sensor entirely
                print("\n>>> TIMER MET: AUTO WATERING TRIGGERED (Cactus Mode)")
                control_pump(True)
                data['pump'] = True
                pump_stop_time = current_time + PUMP_RUN_DURATION
            else:
                # Smart Mode: Interval met, but check if soil is actually dry
                if data['soil'] < AUTO_WATER_THRESHOLD:
                    print("\n>>> SOIL DRY & INTERVAL MET: AUTO WATERING TRIGGERED")
                    control_pump(True)
                    data['pump'] = True
                    pump_stop_time = current_time + PUMP_RUN_DURATION

        # --- WEB SERVER LOGIC ---
        try:
            conn, addr = s.accept()
            conn.settimeout(1.0) 
            
            try:
                request = str(conn.recv(1024))
                
                # Manual Water ON
                if '/water/on' in request:
                    control_pump(True)
                    data['pump'] = True
                    pump_stop_time = time.time() + PUMP_RUN_DURATION
                    last_water_time = time.time() 
                    conn.send('HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n')
                
                # Manual Water OFF (Emergency Stop)
                elif '/water/off' in request:
                    control_pump(False)
                    data['pump'] = False
                    pump_stop_time = 0 
                    last_water_time = time.time() 
                    conn.send('HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n')
                
                # Toggle Master Auto-Mode
                elif '/auto/toggle' in request:
                    auto_mode_enabled = not auto_mode_enabled
                    last_water_time = time.time()
                    conn.send('HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n')
                    
                # Save Configuration Settings (From the HTML Form)
                elif '/config?' in request:
                    try:
                        # Parse URL parameters manually (MicroPython doesn't have urllib)
                        params = request.split('/config?')[1].split(' ')[0]
                        for param in params.split('&'):
                            key, val = param.split('=')
                            if key == 'interval':
                                water_interval = int(val)
                            elif key == 'ignore':
                                ignore_moisture = (val == '1')
                        print(f"\n>>> SETTINGS SAVED: Interval={water_interval}s, IgnoreMoist={ignore_moisture}")
                    except Exception as e:
                        print("Parse error on config:", e)
                    last_water_time = time.time() # Reset clock when settings change
                    conn.send('HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n')
                    
                elif '/api/readings' in request:
                    conn.send('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
                    conn.send(json.dumps(data).encode('utf-8'))
                    
                elif '/log' in request: 
                    try:
                        with open(LOG_FILE, 'r') as f:
                            csv_data = f.read()
                        conn.send('HTTP/1.1 200 OK\r\nContent-Type: text/csv\r\nContent-Disposition: attachment; filename="datalog.csv"\r\n\r\n')
                        conn.send(csv_data)
                    except OSError:
                        conn.send('HTTP/1.1 404 Not Found\r\n\r\nNo log file yet.')
                        
                # Web Dashboard
                else:
                    pump_status = "RUNNING 🟢" if data["pump"] else "OFF 🔴"
                    auto_status = "ACTIVE 🟢" if auto_mode_enabled else "PAUSED 🔴"
                    mode_text = "Timer Mode (Ignore Soil)" if ignore_moisture else "Smart Mode (Check Soil)"
                    
                    toggle_btn_color = "#e67e22" if auto_mode_enabled else "#27ae60"
                    toggle_btn_text = "⏸️ PAUSE AUTO-WATER" if auto_mode_enabled else "▶️ RESUME AUTO-WATER"

                    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Pico Garden</title><meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                    body{{font-family:Arial;text-align:center;background:#eef2f3;padding:20px;}} 
                    .card{{max-width:350px;margin:0 auto;background:white;padding:25px;border-radius:12px;box-shadow:0 4px 10px rgba(0,0,0,0.1); box-sizing:border-box;}}
                    .btn{{display:block;color:white;padding:15px;text-decoration:none;border-radius:8px;margin-top:15px;font-weight:bold; cursor:pointer; border:none; width:100%; box-sizing:border-box;}}
                    .btn-group{{display:flex;gap:10px;margin-top:15px;}}
                    .btn-group .btn{{margin-top:0; flex:1;}}
                    .btn-water{{background:#3498db;}} .btn-water:active{{background:#2980b9;}}
                    .btn-stop{{background:#e74c3c;}} .btn-stop:active{{background:#c0392b;}}
                    .btn-save{{background:#8e44ad;}} .btn-save:active{{background:#732d91;}}
                    .btn-log{{background:#2c3e50;margin-top:25px;}}
                    .settings-box{{background:#f8f9fa; border:1px solid #ddd; padding:15px; border-radius:8px; margin-top:20px; text-align:left; box-sizing:border-box;}}
                    .settings-box label{{font-size:13px; font-weight:bold; color:#555; display:block; margin-bottom:5px;}}
                    select{{width:100%; padding:10px; margin-bottom:15px; border-radius:5px; border:1px solid #ccc; font-size:14px; box-sizing:border-box;}}
                    h1{{color:#2980b9;margin:0;font-size:3em;}}
                    </style></head><body>
                    <div class="card">
                    <h2 style="margin-bottom: 5px;">🪴 The Thirsty Pi</h2>
                    <p style="color:#7f8c8d; font-style:italic; font-size: 14px; margin-top:0; margin-bottom:20px; line-height: 1.4;">
                        Smartly water your thirsty plants. Enjoy your vacation with total peace of mind!
                    </p>
                    
                    <h1>{data['soil']}%</h1><p style="color:#7f8c8d; margin-top:5px;">Soil Moisture</p>
                    <p style="margin-bottom:5px;">🌡️ Temp: <b>{data['temp']}°C</b> &nbsp;|&nbsp; 💧 Hum: <b>{data['hum']}%</b></p>
                    <p style="margin-top:0; color:#7f8c8d; font-size:14px;">(Feels like {data['real_feel']}°C)</p>
                    <hr>
                    <p>Pump Status: <b>{pump_status}</b></p>
                    <p>Auto Master Switch: <b>{auto_status}</b></p>
                    <p style="color:#8e44ad; font-size:14px;">Current Logic: <b>{mode_text}</b></p>
                    
                    <div class="btn-group">
                        <a href="/water/on" class="btn btn-water">🌊 WATER</a>
                        <a href="/water/off" class="btn btn-stop">🛑 STOP</a>
                    </div>
                    <a href="/auto/toggle" class="btn" style="background:{toggle_btn_color};">{toggle_btn_text}</a>
                    
                    <div class="settings-box">
                        <form action="/config" method="GET">
                            <label>Watering Frequency (Interval)</label>
                            <select name="interval">
                                {make_opt(60, '1 Minute (Test Mode)', water_interval)}
                                {make_opt(3600, '1 Hour', water_interval)}
                                {make_opt(43200, '12 Hours', water_interval)}
                                {make_opt(86400, '24 Hours', water_interval)}
                                {make_opt(259200, '3 Days', water_interval)}
                                {make_opt(604800, '1 Week', water_interval)}
                            </select>
                            
                            <label>Sensor Mode</label>
                            <select name="ignore">
                                {make_opt(0, 'Smart Mode (Wait for Dry Soil)', 1 if ignore_moisture else 0)}
                                {make_opt(1, 'Timer Mode (Ignore Soil / For Cactus)', 1 if ignore_moisture else 0)}
                            </select>
                            <button type="submit" class="btn btn-save">💾 SAVE SCHEDULE</button>
                        </form>
                    </div>

                    <a href="/log" class="btn btn-log">📊 DOWNLOAD LOGS</a>
                    <p><small style="color:#bdc3c7;">Auto-refreshes 8s</small></p></div>
                    
                    <script>
                        let timer = setTimeout(function(){{location.reload();}}, 8000);
                        document.querySelectorAll('select').forEach(el => {{
                            el.addEventListener('focus', () => clearTimeout(timer));
                        }});
                    </script>
                    </body></html>"""
                    
                    conn.send('HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                    conn.send(html.encode('utf-8'))
            
            except OSError:
                pass 
            finally:
                conn.close() 
                
        except OSError:
            pass 
        
        time.sleep(0.2) 

finally:
    print("\n[!] Program interrupted or stopped.")
    print("[!] Clearing all hardware pins...")
    control_pump(False)
    try:
        s.close()
    except:
        pass
    print("Cleanup complete. Safe to exit.")
