# Private mobile reader

This is a separate, single-library private service. Do not expose the desktop `app.web.app`.

Required environment variables: `RESEARCHDOCK_PUSH_TOKEN` and `RESEARCHDOCK_READ_TOKEN`, distinct random values of at least 32 characters. Persist `/data`, place the service behind trusted HTTPS, and bind the container HTTP port to loopback on the host. Never commit actual host names, credentials, TLS keys or reader data.

Run the Mac publisher explicitly with `RESEARCHDOCK_SYNC_URL`, `RESEARCHDOCK_PUSH_TOKEN`, and `python -m app.mobile_sync --watch`. It uploads changed live documents and already-generated summaries every 15 seconds without model requests. No source authentication or model credentials are included.

Current preview: private list, body cache, industry/company filtering; local-only reading/favourites, foreground change checks every 30 seconds, complete source attachment inventories, cached images, PDF page previews, and on-demand audio/workbook originals. Remote deletion events and authenticated cached image/PDF assets are supported. Multi-device reading state merge and cross-page snapshot consistency are pending. APK requires HTTPS and stores the reader token using Android Keystore. CI generates a debug-signed preview APK, not a stable production signing identity.


### On-demand originals (0.9)

Deploy the matching cloud and Android versions before restarting the Mac publisher. Source credentials remain on the Mac. Read-token clients can enqueue only attachments already present in a live document manifest; the push token alone can list and complete jobs. The queue is idempotent, bounded to 100 pending requests and uses at most two background source-download tasks in watch mode (one-shot commands process up to three). The Mac verifies current revision and archived membership, validates HTTPS source domains, file signatures and size, then streams the original into the private mirror. No transcription, PDF parsing or model requests occur.

Set the reverse proxy body limit to at least 100MB and upstream timeout to 180s; application limits remain 100,000,000 bytes per original. Preserve TLS, request limits, separate tokens and the existing container restrictions. The cloud never receives source authorization or signed download URLs. Missing and failed originals remain listed; failed requests require a user retry. The Mac must be awake and online.

Android caches requested originals in private app storage. Its non-exported content provider grants temporary read access to one cached file when the reader explicitly opens it in another app. No broad storage permission is required. Offline operation supports files already downloaded to that phone; reading status remains device-local.


### Collection health and daily research (0.11)

Deploy the new cloud before restarting the Mac publisher. The publisher posts a whitelisted source-health heartbeat even when no document changes; it does not advance the document cursor. Android distinguishes source collection, publisher heartbeat, cloud document updates and successful phone checks. Source failures still require Mac-side action; refreshing the phone does not trigger source collection. Current-revision key points, risks and first-import timestamps are also mirrored without new model calls.
