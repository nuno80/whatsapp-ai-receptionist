#!/usr/bin/env zsh

# 1. Spostati nella cartella corretta
cd /home/nuno/programmazione/whatsapp-ai-receptionist/whatsapp-ai-receptionist || exit

# 2. Crea il virtual environment se non esiste già
if [ ! -d ".venv" ]; then
    echo "=> Creazione del virtual environment in corso..."
    python3 -m venv .venv
fi

# 3. Attiva il virtual environment
echo "=> Attivazione del venv..."
source .venv/bin/activate

# 4. Installa le dipendenze (se sono già installate sarà velocissimo)
echo "=> Controllo e installazione dipendenze..."
pip install -r requirements.txt

# 5. Controlla l'esistenza del file .env
if [ ! -f ".env" ]; then
    echo "=> File .env non trovato! Copio .env.example in .env..."
    cp .env.example .env
    echo "⚠️  ATTENZIONE: Ricordati di inserire le tue chiavi nel file .env!"
fi

# 6. Carica esplicitamente le variabili d'ambiente
set -a
source .env
set +a

# 7. Trap per chiudere tutto in modo pulito: 
# Quando premi Ctrl+C per fermare Ngrok, questo comando ucciderà anche Uvicorn in background.
trap 'echo -e "\n=> Chiusura in corso..."; kill $(jobs -p) 2>/dev/null; echo "=> App terminata con successo."; exit' SIGINT SIGTERM

# 8. Avvia Uvicorn (il server python) in BACKGROUND (& alla fine)
echo "=> Avvio del server FastAPI (Uvicorn) in background..."
uvicorn core.main:app --reload --port 8000 &

# Aspettiamo 2 secondi per far avviare il server
sleep 2

# 9. Avvia Ngrok in PRIMO PIANO
echo "=> Avvio di Ngrok sulla porta 8000..."
echo "=> Quando Ngrok si apre, copia l'URL 'Forwarding' (https://...) e aggiungi /webhook su Meta."
echo "=> Premi Ctrl+C per fermare tutto."
sleep 2
ngrok http 8000
