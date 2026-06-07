import os
import time
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import oci
import requests

# --- DUMMY SERVER PER I HEALTH CHECK DI KOYEB ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, format, *args):
        pass # Disattiva i log del server web per tenere pulita la console

def start_health_check_server():
    port = int(os.getenv("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Server di Health Check avviato sulla porta {port}")
    server.serve_forever()

# --- LOGICA DEL BOT TELEGRAM & OCI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Errore nell'invio del messaggio Telegram: {response.text}")
    except Exception as e:
        print(f"Errore di connessione a Telegram: {e}")

def get_oci_config():
    private_key = os.getenv("OCI_PRIVATE_KEY")
    if private_key and "\\n" in private_key:
        private_key = private_key.replace("\\n", "\n")

    config = {
        "user": os.getenv("OCI_USER_OCID"),
        "fingerprint": os.getenv("OCI_FINGERPRINT"),
        "tenancy": os.getenv("OCI_TENANCY_OCID"),
        "region": os.getenv("OCI_REGION"),
        "key_content": private_key
    }
    
    for key, val in config.items():
        if not val:
            print(f"Variabile mancante per la configurazione OCI: {key}")
            sys.exit(1)
            
    return config

def main():
    print("Avvio dello script di Auto-Provisioning OCI...")
    config = get_oci_config()
    
    # Avvia il server web fittizio in un thread separato
    threading.Thread(target=start_health_check_server, daemon=True).start()
    
    try:
        compute_client = oci.core.ComputeClient(config)
    except Exception as e:
        print(f"Errore di inizializzazione del client OCI: {e}")
        sys.exit(1)

    # Log dei parametri di configurazione per verifica iniziale
    compartment_id = os.getenv("OCI_COMPARTMENT_ID")
    availability_domain = os.getenv("OCI_AD")
    image_id = os.getenv("OCI_IMAGE_ID")
    subnet_id = os.getenv("OCI_SUBNET_ID")
    display_name = os.getenv("OCI_DISPLAY_NAME", "Koyeb-ARM-Instance")

    print("--- Parametri di Avvio Istanza ---")
    print(f"Compartment ID:      {compartment_id}")
    print(f"Availability Domain: {availability_domain}")
    print(f"Image ID:            {image_id}")
    print(f"Subnet ID:           {subnet_id}")
    print(f"Display Name:        {display_name}")
    print(f"Shape:               VM.Standard.A1.Flex (4 oCPUs, 24 GB RAM)")
    print("----------------------------------")

    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment_id,
        availability_domain=availability_domain,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_id,
            assign_public_ip=True
        ),
        metadata={
            "ssh_authorized_keys": os.getenv("OCI_SSH_PUBLIC_KEY")
        },
        display_name=display_name
    )

    send_telegram_message("🤖 *Script avviato su Koyeb!* Inizio i tentativi per la risorsa ARM.")

    while True:
        try:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Tentativo di creazione istanza...")
            response = compute_client.launch_instance(launch_details)
            
            instance = response.data
            msg = (
                f"🎉 *Successo! Istanza creata.*\n\n"
                f"*Nome:* {instance.display_name}\n"
                f"*ID:* `{instance.id}`\n"
                f"*Stato:* {instance.lifecycle_state}\n"
                f"Lo script si interromperà ora."
            )
            print(msg)
            send_telegram_message(msg)
            break
            
        except oci.exceptions.ServiceError as e:
            # Rileva se si tratta di un problema di capacità o di un altro errore di servizio
            is_capacity_issue = (
                e.status == 500 or 
                e.status == 429 or 
                (e.message and "out of host capacity" in e.message.lower())
            )
            
            if is_capacity_issue:
                print(f"Capacità non disponibile.")
                print(f"  Stato HTTP: {e.status}")
                print(f"  Codice:     {e.code}")
                print(f"  Messaggio:  {e.message.strip() if e.message else 'Nessun dettaglio aggiuntivo'}")
            else:
                print("Errore del servizio OCI rilevato:")
                print(f"  Stato HTTP: {e.status}")
                print(f"  Codice:     {e.code}")
                print(f"  Messaggio:  {e.message}")
                print(f"  Request ID: {e.request_id}")
                
                # Interrompi lo script se le credenziali o i parametri strutturali sono errati
                if e.status in [400, 401, 403, 404]:
                    send_telegram_message(
                        f"⚠️ *Script interrotto:* Errore critico ({e.status}).\n"
                        f"*Codice:* `{e.code}`\n"
                        f"*Messaggio:* {e.message}"
                    )
                    sys.exit(1)
                    
        except Exception as e:
            print(f"Errore imprevisto durante la chiamata API: {e}")
            
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
