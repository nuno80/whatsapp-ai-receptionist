# VPS Deployment Checklist

## 1. Environment Secrets Setup
Create a `.env` file on your VPS based on `.env.example`.
Required keys:
- `ANTHROPIC_API_KEY`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_VERIFY_TOKEN` (your chosen token)
- `GOOGLE_SERVICE_ACCOUNT_JSON` (base64 encoded JSON)
- `GOOGLE_CALENDAR_ID`
- `GOOGLE_CALENDAR_OWNER_EMAIL`
- `STRIPE_API_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `INTERNAL_SECRET` (for cron jobs)

## 2. DNS and SSL (Caddy)
- Point your domain's A record (and AAAA if using IPv6) to your VPS IP address.
- In your `.env` file, set `DOMAIN=your-public-domain.com`.
- Caddy will automatically provision and renew Let's Encrypt TLS certificates.

## 3. Stripe Webhook Endpoint
- In the Stripe Dashboard, go to Developers > Webhooks.
- Add an endpoint pointing to: `https://<YOUR-DOMAIN>/webhook/stripe`
- Select the `checkout.session.completed` event.
- Copy the Signing Secret and set it as `STRIPE_WEBHOOK_SECRET` in your `.env`.

## 4. Meta WhatsApp Business App
- In the Meta Developer Portal, go to WhatsApp > Configuration.
- Edit the webhook URL to: `https://<YOUR-DOMAIN>/webhook`
- Enter your `WHATSAPP_VERIFY_TOKEN`.
- Subscribe to the `messages` event field.

## 5. Google Service Account
- Go to Google Cloud Console.
- Create a Service Account and download the JSON key.
- Base64 encode the JSON file: `base64 -w 0 credentials.json`
- Set the output as `GOOGLE_SERVICE_ACCOUNT_JSON` in your `.env`.
- Ensure the Service Account email is shared with "Make changes to events" permission on your target Google Calendar.

## 6. Running the Stack
- Start the application using Docker Compose:
  ```bash
  docker compose up -d
  ```
- To view logs:
  ```bash
  docker compose logs -f app
  ```
