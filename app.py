# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)
CORS(app)  # Permite peticiones desde el navegador Web

def db_connection():
    conn = sqlite3.connect("arguss_domotica.db")
    conn.row_factory = sqlite3.Row
    return conn

# Inicializar Base de Datos
def init_db():
    conn = db_connection()
    cursor = conn.cursor()
    
    # Tabla de configuraciones de termostato y usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            departamento TEXT PRIMARY KEY,
            target_temp REAL DEFAULT 22.0,
            temp_low REAL DEFAULT 20.0,
            temp_high REAL DEFAULT 25.0,
            mode TEXT DEFAULT 'auto',
            heating_active INTEGER DEFAULT 0,
            cooling_active INTEGER DEFAULT 0
        )
    ''')
    
    # Tabla de lecturas del ESP32
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lecturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_id TEXT,
            tipo TEXT,
            valor REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insertar valores iniciales si no existen
    cursor.execute("INSERT OR IGNORE INTO configuracion (departamento) VALUES ('Departamento 1')")
    conn.commit()
    conn.close()

init_db()

# -------------------------------------------------------------
# RUTAS DE API PARA EL NAVEGADOR WEB Y ESP32
# -------------------------------------------------------------

# 1. Obtener estado completo (Usado por la Web y la ESP32)
@app.route('/api/status', methods=['GET'])
def get_status():
    conn = db_connection()
    cursor = conn.cursor()
    
    config = cursor.execute("SELECT * FROM configuracion WHERE departamento = 'Departamento 1'").fetchone()
    
    # Obtener última lectura de temperatura
    last_temp = cursor.execute(
        "SELECT valor FROM lecturas WHERE tipo = 'temp' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    
    conn.close()
    
    current_temp = last_temp['valor'] if last_temp else 20.0
    
    return jsonify({
        "thermostat": {
            "target": config['target_temp'],
            "low": config['temp_low'],
            "high": config['temp_high'],
            "mode": config['mode'],
            "heating": bool(config['heating_active']),
            "cooling": bool(config['cooling_active']),
            "current_temp": current_temp,
            "online": True
        }
    })

# 2. Guardar configuración del termostato desde la Web
@app.route('/api/thermostat', methods=['POST'])
def update_thermostat():
    data = request.json
    conn = db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE configuracion 
        SET target_temp = COALESCE(?, target_temp),
            mode = COALESCE(?, mode),
            temp_low = COALESCE(?, temp_low),
            temp_high = COALESCE(?, temp_high)
        WHERE departamento = 'Departamento 1'
    ''', (data.get('target'), data.get('mode'), data.get('low'), data.get('high')))
    
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

# 3. Endpoint exclusivo para el ESP32 (Envía sensores y recibe estado de relés)
@app.route('/api/esp32/update', methods=['POST'])
def esp32_update():
    data = request.json  # Ej: {"temp": 21.5, "hum": 50}
    conn = db_connection()
    cursor = conn.cursor()
    
    temp = data.get('temp')
    hum = data.get('hum')
    
    if temp is not None:
        cursor.execute("INSERT INTO lecturas (sensor_id, tipo, valor) VALUES ('temp-estar', 'temp', ?)", (temp,))
    if hum is not None:
        cursor.execute("INSERT INTO lecturas (sensor_id, tipo, valor) VALUES ('hum-estar', 'hum', ?)", (hum,))
        
    # Lógica de Control Automático de Termostato
    config = cursor.execute("SELECT * FROM configuracion WHERE departamento = 'Departamento 1'").fetchone()
    heating = config['heating_active']
    cooling = config['cooling_active']
    
    if config['mode'] == 'auto' and temp is not None:
        if temp < config['temp_low']:
            heating = 1
            cooling = 0
        elif temp >= config['temp_high']:
            heating = 0
            cooling = 1
        else:
            heating = 0
            cooling = 0
            
        cursor.execute(
            "UPDATE configuracion SET heating_active = ?, cooling_active = ? WHERE departamento = 'Departamento 1'",
            (heating, cooling)
        )
    
    conn.commit()
    conn.close()
    
    # Devuelve órdenes al ESP32 para activar/desactivar sus relés
    return jsonify({
        "relay_heating": bool(heating),
        "relay_cooling": bool(cooling)
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)