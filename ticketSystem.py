import yaml
import socket
from datetime import datetime
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config
import time
import requests

TELEGRAM_TOKEN = "8432776653:AAEB0drd0sAx2beUrgOEk-umnfcwoOw8Q4Y"
TELEGRAM_CHAT_ID = "-1003463891028"

# Funciones auxiliares

def cargar_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def guardar_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f)

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"[ERROR TELEGRAM] {e}")


def crear_ticket(tipo, dispositivo, descripcion, responsables, tickets):
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
    
    # NOTIFICACIÓN A TELEGRAM
    enviar_telegram(f"*TICKET CREADO*\nTipo: {tipo}\nDispositivo: {dispositivo}\nDescripción: {descripcion}\nAsignado a: {asignado_a}")

    print(f"[TICKET CREADO] {tipo.upper()} en {dispositivo} asignado a {asignado_a}")
    return tickets

def cerrar_ticket(ticket_id, tickets):
    for ticket in tickets["tickets"]:
        if ticket["id"] == ticket_id and ticket["estado"] == "abierto":
            ticket["estado"] = "cerrado"
            ticket["fecha_cierre"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # NOTIFICACIÓN A TELEGRAM
            enviar_telegram(f"*TICKET CERRADO*\nID: {ticket_id}\nTipo: {ticket['tipo']}\nDispositivo: {ticket['dispositivo']}")

            print(f"[TICKET CERRADO] ID {ticket_id} - {ticket['tipo']} en {ticket['dispositivo']}")
            return True
    return False

# Funciones de simulación de fallos reales

def enviar_syslog(host_src, message, dest_ip="127.0.0.1", dest_port=5140):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # mensaje en estilo RFC3164 simple: "<PRI>TIMESTAMP HOST TAG: MSG"
    syslog_msg = f"{host_src} {message}"
    sock.sendto(syslog_msg.encode(), (dest_ip, dest_port))
    sock.close()

def simular_interfaz_caida(nr, host_name):
    try:
        resultado = nr.filter(name=host_name).run(
            task=netmiko_send_config,
            config_commands=[
                "interface Ethernet0/1",
                "shutdown"
            ]
        )

        enviar_telegram(f"⚠️ *ALERTA*: Interfaz caída en {host_name}\nEthernet0/1 administratively DOWN")

        print(f"[SIMULACIÓN DE FALLO #1] Interfaz Ethernet0/1 apagada en {host_name}")
        # Enviar syslog que será analizado por syslog_receiver
        enviar_syslog(host_name, "Interface Ethernet0/1 changed state to administratively down", dest_ip="127.0.0.1", dest_port=5140)
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo simular fallo de interfaz en {host_name}: {e}")
        return False

def solucionar_interfaz_caida(nr, host_name):
    try:
        resultado = nr.filter(name=host_name).run(
            task=netmiko_send_config,
            config_commands=[
                "interface Ethernet0/1",
                "no shutdown"
            ]
        )

        enviar_syslog(host_name, "Interface Ethernet0/1 changed state to up", dest_ip="127.0.0.1", dest_port=5140)
        enviar_telegram(f"🛠 *Solución aplicada*: Interfaz restaurada en {host_name}")

        print(f"[FALLO RESUELTO] Interfaz Ethernet0/1 activada en {host_name}")
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo solucionar interfaz en {host_name}: {e}")
        return False

def simular_ruta_fallida(nr, host_name):
    try:
        resultado = nr.filter(name=host_name).run(
            task=netmiko_send_config,
            config_commands=[
                "router ospf 1",
                "shutdown"
            ]
        )

        enviar_telegram(f"⚠️ *ALERTA*: OSPF caído en {host_name}\nAdjacency DOWN")

        print(f"[SIMULACIÓN DE FALLO #2] OSPF desactivado en {host_name}")

        # Enviar syslog de caída de OSPF
        enviar_syslog(
            host_name,
            "OSPF-5-ADJCHG: OSPF adjacency DOWN due to shutdown",
            dest_ip="127.0.0.1",
            dest_port=5140
        )

        return True
    except Exception as e:
        print(f"[ERROR] No se pudo simular fallo OSPF en {host_name}: {e}")
        return False

def solucionar_ruta_fallida(nr, host_name):
    try:
        resultado = nr.filter(name=host_name).run(
            task=netmiko_send_config,
            config_commands=[
                "router ospf 1",
                "no shutdown"
            ]
        )
        print(f"[FALLO RESUELTO] OSPF reactivado en {host_name}")

        # Enviar syslog indicando recuperación
        enviar_syslog(
            host_name,
            "OSPF-5-ADJCHG: OSPF adjacency UP after reactivation",
            dest_ip="127.0.0.1",
            dest_port=5140
        )
        enviar_telegram(f"🛠 *Solución aplicada*: OSPF restaurado en {host_name}")


        return True
    except Exception as e:
        print(f"[ERROR] No se pudo solucionar OSPF en {host_name}: {e}")
        return False

#  Ciclo de simulación 

def ciclo_fallos(nr, responsables, tickets, hosts_list):
    ciclo = 0
    tipos_fallos = ["interfaz_caida", "ruta_fallida"]
    
    while True:
        # Seleccionar tipo de fallo y dispositivo de forma rotativa
        tipo_fallo = tipos_fallos[ciclo % len(tipos_fallos)]
        host_name = hosts_list[ciclo % len(hosts_list)]
        
        print(f"\n{'='*60}")
        print(f"CICLO #{ciclo + 1}")
        print(f"{'='*60}")
        
        # Generar fallo
        print(f"\n[FASE 1] Generar fallo: {tipo_fallo} en {host_name}")
        fallo_exitoso = False
        
        if tipo_fallo == "interfaz_caida":
            fallo_exitoso = simular_interfaz_caida(nr, host_name)
            descripcion = "Interfaz Ethernet0/1 DOWN"
        elif tipo_fallo == "ruta_fallida":
            fallo_exitoso = simular_ruta_fallida(nr, host_name)
            descripcion = "OSPF inactivo"
        
        # Crear ticket si el fallo se simuló exitosamente
        if fallo_exitoso:
            tickets = crear_ticket(tipo_fallo, host_name, descripcion, responsables, tickets)
            guardar_yaml("inventory/tickets.yaml", tickets)
        
        print(f"*10 segundos de espera para resolverlo* ")
        time.sleep(10)
        
        # Resolver el fallo
        print(f"\n[FASE 2] Resolver fallo: {tipo_fallo} en {host_name}")
        
        if tipo_fallo == "interfaz_caida":
            solucionar_interfaz_caida(nr, host_name)
        elif tipo_fallo == "ruta_fallida":
            solucionar_ruta_fallida(nr, host_name)
        
        # Cerrar el último ticket creado para este dispositivo y tipo
        for ticket in reversed(tickets["tickets"]):
            if (ticket["dispositivo"] == host_name and 
                ticket["tipo"] == tipo_fallo and 
                ticket["estado"] == "abierto"):
                cerrar_ticket(ticket["id"], tickets)
                guardar_yaml("inventory/tickets.yaml", tickets)
                break
        
        print(f"*10 segundos antes del próximo ciclo* ")
        time.sleep(10)
        
        ciclo += 1

# Ejecución principal

if __name__ == "__main__":
    print("Sistema de monitoreo con simulación de fallos reales")
    
    nr = InitNornir(config_file="config.yaml")
    responsables = cargar_yaml("inventory/responsibles.yaml")
    tickets = cargar_yaml("inventory/tickets.yaml")
    
    # Obtener lista de hosts
    hosts_list = list(nr.inventory.hosts.keys())
    
    print(f"\nDispositivos disponibles: {hosts_list}")
    print("Presionar Ctrl+C para detener el monitoreo\n")

# Revisar si hay tickets abiertos antes de iniciar la simulación de fallos
    for ticket in (tickets["tickets"]):
        if (ticket["estado"] == "abierto"):
            cerrar_ticket(ticket["id"], tickets)
            guardar_yaml("inventory/tickets.yaml", tickets)
            
# Inciar simulación de fallos
    try:
        ciclo_fallos(nr, responsables, tickets, hosts_list)
    except KeyboardInterrupt:
        print("\n\n[DETENIDO] Monitoreo finalizado por el usuario")
        guardar_yaml("inventory/tickets.yaml", tickets)
        print("Tickets guardados correctamente")