# Piano di modifica: WhatsApp AI Receptionist → B&B Roma (1 camera)

## Contesto del progetto

Partiamo dal repository open source [nuno80/whatsapp-ai-receptionist](https://github.com/nuno80/whatsapp-ai-receptionist) come starter kit. È un bot WhatsApp in Python/FastAPI che usa l'API Anthropic (Claude) per gestire conversazioni, estrae l'intento del cliente e lo traduce in eventi su Google Calendar, con Redis per lo stato e promemoria automatici.

Il progetto originale è pensato per attività con **appuntamenti orari** (dentisti, saloni). Va adattato per **soggiorni multi-notte** in un B&B con **una sola camera doppia**.

**Modello AI**: Claude Sonnet 5 (`claude-sonnet-5`), via API Anthropic diretta (no LangChain, chiamate dirette come nel progetto originale).

**Struttura repo originale**:
```
whatsapp-ai-receptionist/
├── core/
│   ├── main.py          # FastAPI app, webhook handlers, intent routing
│   ├── ai.py            # Claude integration, system prompt, intent extraction
│   ├── whatsapp.py      # WhatsApp Cloud API client
│   ├── transcribe.py    # Whisper audio transcription
│   ├── history.py       # Conversation history (Redis / in-memory)
│   └── phone.py         # Phone number normalization
├── config/
│   └── loader.py        # YAML config con ${ENV_VAR} substitution
├── modules/
│   ├── booking/
│   │   └── calendar.py  # Google Calendar con slot locking
│   └── payments/
│       └── mercadopago.py
├── reminders/
│   └── scheduler.py
├── knowledge/
│   └── client.txt
├── config.yaml
└── tests/
```

---

## Requisiti raccolti (specifiche di business)

- **Camera**: 1 doppia, prezzo fisso indipendentemente dal numero di ospiti (1 o 2 persone)
- **Check-in/check-out**: orari fissi di default, ma editabili a mano in un file di config
- **Prenotazioni same-day**: accettate
- **Prezzo**: variabile per periodo (Roma ha eventi che alzano i prezzi), gestito manualmente dal proprietario in un file/tabella "date da–a → prezzo/notte", **nessuna regola automatica** (no weekend+20% automatico: tutto a discrezione del proprietario)
- **Minimum stay**: variabile per periodo, stessa logica manuale
- **Cancellazione**: parametro singolo "giorni prima" → gratis entro quel termine, altrimenti pagamento intero (non variabile per stagione)
- **Pagamento**: 3 modalità possibili (acconto / saldo in loco / pagamento completo online), impostate **manualmente dal proprietario**, valide finché non le ricambia lui (nessuna regola automatica legata alle date)
- **Gateway di pagamento**: **Stripe** (vedi confronto commissioni sotto)
- **Fatturazione**: NON automatizzata in questa fase — il proprietario fa le fatture a mano. Backlog per il futuro.
- **OTA (Booking/Airbnb)**: non ancora attive, ma da prevedere subito un modulo di import iCal (sola lettura) per bloccare le date quando verranno attivate
- **Google Calendar**: unico calendario master (no channel manager esterno)
- **Lingue**: multilingua — italiano, inglese, spagnolo, francese, tedesco. Rilevamento automatico della lingua del cliente.
- **Knowledge base**: il proprietario prepara guide (parcheggio, ristoranti, itinerari, regole della casa) **già tradotte in tutte e 5 le lingue** (no traduzione automatica in tempo reale, per garantire accuratezza di indirizzi/orari)
- **Persona del bot**: nome "Giulia" (modificabile facilmente, è solo config), tono cordiale-professionale (non troppo informale), si dichiara esplicitamente assistente virtuale del B&B
- **Notifiche**: ogni nuova richiesta (prenotazione/cancellazione/modifica) genera un messaggio WhatsApp a TUTTI i membri della famiglia autorizzati (4 persone)
- **Approvazione manuale**: obbligatoria in questa fase iniziale. Il bot NON conferma nulla in autonomia — aspetta "OK" da un umano.
- **Logica di conferma multi-utente**: quando arriva una richiesta di approvazione, va a tutti e 4. Chi risponde per primo con conferma "chiude" la richiesta. Agli altri 3 arriva un messaggio automatico tipo *"Prenotazione gestita da [nome utente]"*. Serve un lock atomico (via Redis) per evitare race condition se rispondono nello stesso istante.
- **Dashboard**: non serve, Google Calendar è sufficiente come vista
- **Sito web**: Next.js, fase 1 solo vetrina (foto, descrizione, contatti) + pulsante che apre chat WhatsApp diretta. Fase 2 (backlog): calendario disponibilità in tempo reale + widget di prenotazione embedded.
- **Infrastruttura**: VPS (non Railway), Docker/docker-compose, dominio da registrare, reverse proxy HTTPS (Caddy consigliato per semplicità di setup certificati automatici)
- **WhatsApp Business**: da configurare da zero (account Meta Developer + numero dedicato)
- **Scala futura**: resterà sempre mono-camera, no multi-property

---

## Confronto gateway di pagamento (verificato)

| Gateway | Commissione online | Canone fisso |
|---|---|---|
| **Stripe** ✅ scelto | 1,5% + €0,25 (carte UE) / 3,25% + €0,25 (carte extra-UE) | Nessuno |
| SumUp Pay by Link | 2,5% flat | Nessuno |
| PayPal | ~3,49% + fissa | Nessuno |

**Stripe è la scelta più economica** per il mix di clienti previsto (italiani + europei), oltre ad avere l'integrazione API migliore per generare link di pagamento dinamici da inviare via WhatsApp.

---

## Elenco modifiche dettagliato, modulo per modulo

### 1. `config.yaml` — ristrutturazione completa
Nuove sezioni da creare:
- **`pricing_periods`**: lista di `{ start_date, end_date, price_per_night }`, editabile a mano, nessuna sovrapposizione ambigua (in caso di overlap, vince il periodo più specifico/ultimo inserito — da decidere una regola chiara in fase di implementazione)
- **`minimum_stay_periods`**: stessa struttura, `{ start_date, end_date, min_nights }`
- **`cancellation_policy`**: `{ free_cancellation_days_before: N }`
- **`payment_mode`**: enum manuale `deposit | full_on_site | full_online`, con eventuale `deposit_percentage` se `deposit`
- **`checkin_checkout`**: `{ checkin_time: "15:00", checkout_time: "10:00" }`, facilmente editabile
- **`bot_persona`**: `{ name: "Giulia", tone: "cordiale-professionale", declares_as_ai: true }`
- **`authorized_approvers`**: lista dei 4 numeri WhatsApp di famiglia autorizzati a ricevere/approvare richieste

### 2. `modules/booking/calendar.py` — riscrittura logica di prenotazione
- Sostituire il modello "slot orario fisso" con intervalli di date (check-in → check-out)
- Rimuovere il controllo `business_hours` (non applicabile a soggiorni multi-notte)
- Calcolo prezzo: sommare il prezzo/notte per ogni notte del soggiorno, leggendo da `pricing_periods` (un soggiorno può attraversare più fasce di prezzo)
- Validazione minimum stay: controllare `minimum_stay_periods` per le date richieste
- Controllo overlap: semplice, essendo una sola camera (nessuna gestione multi-risorsa necessaria)
- Applicare `checkin_checkout` orari fissi agli eventi Google Calendar generati

### 3. Nuovo modulo: `modules/booking/ota_sync.py` — import iCal da OTA
- Job periodico (es. ogni 15-30 min, schedulato) che legge i feed iCal pubblici di Booking.com/Airbnb (quando attivati) e crea eventi di blocco sul Google Calendar master
- **Sola lettura**: OTA → calendario proprietario, mai il contrario (niente scrittura verso le OTA, molto più semplice da mantenere)
- Se non ci sono ancora URL iCal configurati, il modulo resta inattivo senza errori (feature flag in config)

### 4. Nuovo modulo: `modules/approval/approval_flow.py` — approvazione manuale multi-utente
- Ogni richiesta (prenotazione/cancellazione/modifica) genera un record in Redis con stato `pending`, id univoco, e dettagli della richiesta
- Invio del messaggio WhatsApp a tutti i numeri in `authorized_approvers`, con id richiesta embeddato per il matching della risposta
- Alla prima risposta di conferma ricevuta (da uno qualsiasi dei 4): lock atomico su Redis (es. `SETNX` o transazione) per marcare la richiesta come `approved_by: <nome>`, poi eseguire l'azione (creare/cancellare/modificare l'evento calendar) e confermare al cliente
- Messaggio automatico agli altri 3: *"Richiesta [tipo] del [date] gestita da [nome]"*
- Timeout: da definire (es. se nessuno risponde entro X ore, notifica di sollecito) — proporre in fase di implementazione

### 5. `core/ai.py` — prompt, persona e intent extraction
- System prompt aggiornato con persona "Giulia" (nome modificabile in config), tono cordiale-professionale, dichiarazione esplicita di essere assistente virtuale
- Estrazione intento adattata a: check-in, check-out, numero ospiti (max 2), richiesta di cancellazione/modifica con riferimento alla prenotazione esistente
- Rilevamento automatico della lingua del messaggio in arrivo tra le 5 supportate (IT, EN, ES, FR, DE), risposta nella stessa lingua
- "Date pre-calcolate" (design principle del progetto originale, da mantenere): invece di prossimi slot orari liberi, generare i prossimi periodi liberi (range di notti consecutive disponibili) da iniettare nel system prompt
- Caricamento della knowledge base nella lingua rilevata (le 5 versioni preparate dal proprietario)

### 6. `modules/payments/` — sostituzione Mercado Pago → Stripe
- Nuovo client Stripe (Payment Links API o Checkout Session, da valutare in implementazione — Payment Links è più semplice da generare al volo e inviare via WhatsApp)
- Logica applicazione modalità di pagamento: leggere `payment_mode` da config e generare il link/importo corretto (acconto % / importo pieno / nessun link se pagamento in loco)
- Webhook Stripe per conferma pagamento ricevuto → aggiornamento stato prenotazione
- Fatturazione: esplicitamente FUORI SCOPE in questa fase (backlog)

### 7. `reminders/scheduler.py`
- Adattare il promemoria 24h pre-appuntamento in promemoria pre-check-in (es. 24-48h prima), con informazioni pratiche (orario check-in, come arrivare) nella lingua del cliente

### 8. Infrastruttura e deploy
- Passaggio da Railway a **VPS con Docker Compose**: container per l'app FastAPI + Redis
- Reverse proxy HTTPS: **Caddy** consigliato (setup automatico certificati Let's Encrypt, configurazione minima) — alternativa Nginx + Certbot se preferenza diversa
- Dominio: da registrare, necessario sia per il webhook Meta/WhatsApp sia per il sito Next.js
- Account Meta Developer + numero WhatsApp Business dedicato: da creare da zero (serve verifica business)

### 9. Sito web (Next.js) — solo Fase 1 ora
- Vetrina statica: foto, descrizione, posizione, contatti
- Pulsante "Scrivici su WhatsApp" con link diretto (`https://wa.me/<numero>`)
- Nessuna integrazione calendario/pagamento in questa fase

### 10. Backlog esplicito (rimandato volutamente)
- Widget di prenotazione embedded sul sito + calendario disponibilità in tempo reale
- Fatturazione elettronica italiana automatica
- Regole di prezzo/cancellazione automatiche legate a stagione (attualmente tutto manuale)
- Automazione totale senza approvazione manuale (da valutare dopo un periodo di collaudo)
- Timeout/sollecito se nessuno dei 4 approva entro un certo tempo

---

## Note tecniche da tenere presenti in fase di implementazione

- **Costi API**: con Claude Sonnet 5 (pricing introduttivo $2/$10 per milione di token input/output fino al 31 agosto 2026, poi $3/$15), il costo stimato per il volume di un B&B mono-camera è di pochi dollari al mese — non è un fattore critico di design.
- **Prompt caching**: attivarlo per system prompt + knowledge base (contenuto statico ripetuto ad ogni chiamata) per ridurre i costi di input fino al 90%.
- Il tokenizer di Sonnet 5 è cambiato rispetto a versioni precedenti (fino a 1.35x più token per lo stesso testo) — irrilevante al volume previsto, ma da tenere a mente se in futuro si scala.
- Verificare in fase di implementazione la licenza/termini d'uso dei feed iCal di Booking.com e Airbnb (generalmente sono forniti proprio per questo scopo, ma vanno controllati caso per caso quando si attiveranno gli account).

---

## Prossimo passo suggerito

Iniziare l'implementazione partendo da:
1. Fork del repository originale
2. Ristrutturazione `config.yaml` (punto 1) — è la base da cui dipende tutto il resto
3. Riscrittura `modules/booking/calendar.py` (punto 2)
4. Modulo di approvazione manuale (punto 4) — è il punto più delicato, va testato con attenzione
5. A seguire: AI/persona, pagamenti Stripe, iCal sync, deploy
