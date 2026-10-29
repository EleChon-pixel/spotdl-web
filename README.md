# Homelab Music Downloader

A private web queue for spotDL. Paste a Spotify track, album, or playlist URL; spotDL searches YouTube for matching audio and writes MP3 files to `/srv/media/Music`, which Navidrome and Jellyfin already index.

## Deployment

This installation is designed for `homeserver`. Docker binds the app to `127.0.0.1:8765`; Tailscale Serve publishes `/music/` on the existing tailnet-only HTTPS port 8443. It is not exposed to the LAN or public internet. Devices allowed by the tailnet policy can use it without a separate sign-in. Use content you have permission to download.

1. Set `PUID` and `PGID` in a private `.env` file. Keep mode `0600` and do not commit it.
2. Confirm that this user can write to `/srv/media/Music` and the local `data/` directory.
3. Run `docker compose up -d --build` and check `docker compose ps`.
4. On the server, add `tailscale serve --bg --https=8443 --set-path=/music http://127.0.0.1:8765` without resetting the existing `/` route.
5. Open `https://<homeserver-tailnet-name>:8443/music/` on a device allowed by the existing tailnet policy.

The download page and queue API are available to devices allowed by the tailnet policy. Queue and log history live in memory and reset when the container restarts. One job runs at a time, with at most ten queued/running jobs. Downloads use `--overwrite skip`; the app does not intentionally replace existing files. It does not need Spotify credentials or Docker socket access.

The image pins spotDL 4.5.2 and includes FFmpeg. Some YouTube sources may require additional extractor setup; a successful app health check does not establish that every source will download. Test only with content you may download.
