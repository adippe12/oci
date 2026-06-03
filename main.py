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

    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=os.getenv("OCI_COMPARTMENT_ID"),
        availability_domain=os.getenv("OCI_AD"),
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=os.getenv("OCI_IMAGE_ID")
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=os.getenv("OCI_SUBNET_ID"),
            assign_public_ip=True
        ),
        metadata={
            "ssh_authorized_keys": os.getenv("OCI_SSH_PUBLIC_KEY")
        },
        display_name=os.getenv("OCI_DISPLAY_NAME", "Koyeb-ARM-Instance")
    )

    send_telegram_message("🤖 *Script avviato su Koyeb!* Inizio i tentativi per la risorsa ARM.")

    while True:
        try:
            print("Tentativo di creazione istanza...")
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
            break  # Interrompe il ciclo ed esce dallo script con successo
            
        except oci.exceptions.ServiceError as e:
            if e.status == 500 or "Out of host capacity" in e.message or e.status == 429:
                print(f"Capacità non disponibile (Errore {e.status}). Nuovo tentativo a breve...")
            else:
                print(f"Errore del servizio OCI: {e.status} - {e.message}")
                if e.status in [401, 404]:
                    send_telegram_message(f"⚠️ *Script interrotto:* Errore di configurazione credenziali: {e.message}")
                    sys.exit(1)
                    
        except Exception as e:
            print(f"Errore imprevisto: {e}")
            
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
