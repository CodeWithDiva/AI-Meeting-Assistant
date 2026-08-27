# Zoom RTMS webhook setup (development)

The Zoom Event Subscription uses the Webhook method and subscribes to:

- `meeting.rtms_started`
- `meeting.rtms_stopped`

Zoom validates and delivers webhooks to a public HTTPS address. Do not enter a
`127.0.0.1` or `localhost` URL in Zoom. Expose the local endpoint through a
temporary HTTPS tunnel, then use:

`https://<public-tunnel-host>/api/integrations/zoom/webhook`

Set the Marketplace **Secret Token** only in the untracked `.env` file as
`ZOOM_WEBHOOK_SECRET_TOKEN`; never commit or share it. The endpoint responds to
Zoom's `endpoint.url_validation` handshake and verifies signed event requests.
