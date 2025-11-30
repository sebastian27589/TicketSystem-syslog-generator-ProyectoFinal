# syslog_receiver.py
import socket
import re
import yaml
import threading
import requests
from datetime import datetime

# Carga tu YAML de tickets y responsables
def cargar_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)
    

def guardar_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

# ---------- Notificador Telegram ----------
TELEGRAM_BOT_TOKEN = "8432776653:AAEB0drd0sAx2beUrgOEk-umnfcwoOw8Q4Y"
TELEGRAM_CHAT_ID = "-1003463891028"

def notify_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[WARN] Error notificando Telegram: {e}")

# ---------- Gestión de tickets (integrable con tu código) ----------
tickets_path = "inventory/tickets.yaml"
responsibles_path = "inventory/responsibles.yaml"

tickets = cargar_yaml(tickets_path)
responsables = cargar_yaml(responsibles_path)

def crear_ticket(tipo, dispositivo, descripcion):
    asignado_a = responsables["personas"][responsables["responsables"][tipo]]["nombre"]
    nuevo_ticket = {
        "id": len(tickets["tickets"]) + 1,
        "tipo": tipo,
        "dispositivo": dispositivo,
        "descripcion": descripcion,
        "asignado_a": asignado_a,
        "estado": "abierto",
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tickets["tickets"].append(nuevo_ticket)
    guardar_yaml(tickets_path, tickets)
    msg = (f"<b>[TICKET ABIERTO]</b>\nID: {nuevo_ticket['id']}\nTipo: {tipo}\nDispositivo: {dispositivo}\n"
           f"Asig: {asignado_a}\nDesc: {descripcion}\nFecha: {nuevo_ticket['fecha']}")
    print(msg)
    notify_telegram(msg)
    return nuevo_ticket

def cerrar_ticket_por_dispositivo_y_tipo(dispositivo, tipo):
    # cierra el último ticket abierto para ese dispositivo/tipo
    for ticket in reversed(tickets["tickets"]):
        if ticket["dispositivo"] == dispositivo and ticket["tipo"] == tipo and ticket["estado"] == "abierto":
            ticket["estado"] = "cerrado"
            ticket["fecha_cierre"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            guardar_yaml(tickets_path, tickets)
            msg = (f"<b>[TICKET CERRADO]</b>\nID: {ticket['id']}\nTipo: {tipo}\nDispositivo: {dispositivo}\n"
                   f"Asig: {ticket['asignado_a']}\nFecha cierre: {ticket['fecha_cierre']}")
            print(msg)
            notify_telegram(msg)
            return True
    return False

# ---------- Patrones de logs (ajusta según los mensajes reales) ----------
# Ejemplos: "Interface Ethernet0/1, changed state to administratively down"
PATTERN_INTERF_DOWN = re.compile(r"(?:Interface|%INTERFACE%|Interface)\s+([A-Za-z0-9/]+).*down", re.IGNORECASE)
PATTERN_INTERF_UP = re.compile(r"(?:changed state to up|up|line protocol is up|is up)", re.IGNORECASE)

# OSPF: router ospf stopping/starting mensajes comunes pueden variar. Usa keywords.
PATTERN_OSPF_DOWN = re.compile(r"(ospf|OSPF).*(down|shut|stopped|inactive|is down|is inactive)", re.IGNORECASE)
PATTERN_OSPF_UP = re.compile(r"(ospf|OSPF).*(up|started|is up|is active|recovered)", re.IGNORECASE)

# ---------- Servidor UDP de syslog ----------
SYSLOG_UDP_IP = "0.0.0.0"
SYSLOG_UDP_PORT = 5140  # si no tienes permisos para 514 usa >1024, p.ej. 5140

def handle_message(message):
    text = message.strip()
    # Detectar interface down/up
    m_down = PATTERN_INTERF_DOWN.search(text)
    if m_down:
        iface = m_down.group(1)
        dispositivo = infer_device_from_syslog(text)  # función abajo
        crear_ticket("interfaz_caida", dispositivo, f"Interfaz {iface} DOWN (syslog): {text}")
        return

    if PATTERN_INTERF_UP.search(text):
        dispositivo = infer_device_from_syslog(text)
        # cerrar ticket de interfaz
        cerrar_ticket_por_dispositivo_y_tipo(dispositivo, "interfaz_caida")
        return

    # Detectar OSPF
    if PATTERN_OSPF_DOWN.search(text):
        dispositivo = infer_device_from_syslog(text)
        crear_ticket("ruta_fallida", dispositivo, f"OSPF inactivo (syslog): {text}")
        return

    if PATTERN_OSPF_UP.search(text):
        dispositivo = infer_device_from_syslog(text)
        cerrar_ticket_por_dispositivo_y_tipo(dispositivo, "ruta_fallida")
        return

    # Para debugging
    print("[SYSLOG] No match:", text)

def infer_device_from_syslog(msg_text):
    # Intenta extraer hostname del mensaje (RFC3164/5424 suelen poner hostname después del timestamp)
    # Simple heuristic: busca token parecido a R1, SW-SROSARIO o dirección IP
    m = re.search(r"\b([A-Za-z0-9\-_]+)\b", msg_text)
    if m:
        return m.group(1)
    return "unknown_device"

def syslog_udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SYSLOG_UDP_IP, SYSLOG_UDP_PORT))
    print(f"[SYSLOG] Listening UDP on {SYSLOG_UDP_IP}:{SYSLOG_UDP_PORT}")
    while True:
        data, addr = sock.recvfrom(4096)
        try:
            text = data.decode("utf-8", errors="replace")
        except:
            text = str(data)
        threading.Thread(target=handle_message, args=(text,)).start()

if __name__ == "__main__":
    syslog_udp_server()
