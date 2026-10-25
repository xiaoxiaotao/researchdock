# Private mobile reader

This is a separate, single-library private service. Do not expose the desktop `app.web.app`.

Required environment variables: `RESEARCHDOCK_PUSH_TOKEN` and `RESEARCHDOCK_READ_TOKEN`, distinct random values of at least 32 characters. Persist `/data`, place the service behind trusted HTTPS, and bind the container HTTP port to loopback on the host. Never commit actual host names, credentials, TLS keys or reader data.

Run the Mac publisher explicitly with `RESEARCHDOCK_SYNC_URL`, `RESEARCHDOCK_PUSH_TOKEN`, and `python -m app.mobile_sync --watch`. It uploads changed live documents and already-generated summaries every 60 seconds without model requests. No source authentication or model credentials are included.

Current preview: private list, body cache, industry/company filtering; local-only reading/favourites, foreground change checks every 30 seconds, cached images and PDF page previews. Remote deletion events and authenticated cached image/PDF assets are supported. Multi-device reading state merge and cross-page snapshot consistency are pending. APK requires HTTPS and stores the reader token using Android Keystore. CI generates a debug-signed preview APK, not a stable production signing identity.
