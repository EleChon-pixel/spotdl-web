# Homelab Music Downloader

A private web queue for spotDL. Paste a Spotify track, album, or playlist URL; spotDL searches YouTube for matching audio and writes MP3 files to `/srv/media/Music`, which Navidrome and Jellyfin already index.

## Legal notice

This project is only a small web queue around [spotDL](https://github.com/spotDL/spotify-downloader). It contains no copyrighted material and does not bundle spotDL's downloaded content. Downloading from YouTube or Spotify may violate their terms of service and copyright law in your country. Use it only for content you own or have permission to download. You are responsible for how you use it; the author accepts no liability.

## Deployment

This installation is designed for `homeserver`. Docker binds the app to `127.0.0.1:8765`; Tailscale Serve publishes `/music/` on the existing tailnet-only HTTPS port 8443. It is not exposed to the LAN or public internet. The app also requires an explicit allowlist of Tailscale login identities; unauthenticated requests fail closed. Use content you have permission to download.

1. Set `PUID`, `PGID`, and `ALLOWED_TAILSCALE_USERS` in a private `.env` file. Set the last value to your exact Tailscale login (comma-separated for multiple users). Keep `.env` mode `0600` and never commit it.
2. Confirm that this user can write to `/srv/media/Music` and the local `data/` directory.
3. Run `docker compose up -d --build` and check `docker compose ps`.
4. On the server, add `tailscale serve --bg --https=8443 --set-path=/music http://127.0.0.1:8765` without resetting the existing `/` route.
5. Open `https://<homeserver-tailnet-name>:8443/music/` on a device allowed by the existing tailnet policy.

The download page and queue API require both Tailscale Serve identity headers and membership in `ALLOWED_TAILSCALE_USERS`. Keep the container port on host loopback; do not bypass Serve with an alternate reverse proxy, direct LAN publish, or Funnel. A local process able to connect to port 8765 could forge the header, so the host must remain trusted. Restart after setting the allowlist. Queue and log history live in memory and reset when the container restarts. One job runs at a time, with at most ten queued/running jobs. Downloads use `--overwrite skip`; the app does not intentionally replace existing files. It does not need Spotify credentials or Docker socket access.

The image pins spotDL 4.5.2 and includes FFmpeg. Some YouTube sources may require additional extractor setup; a successful app health check does not establish that every source will download. Test only with content you may download.


## Hardening and checks

- Requests without an allowed `Tailscale-User-Login` header receive 403; missing allowlist configuration returns 503, except for `/healthz`. Tailscale Serve removes spoofed identity headers supplied by clients and inserts the authenticated user's identity.
- Queue history is shown only to its submitting user; each user may have at most two active jobs, with ten globally. At least 2 GiB of free music-volume space must remain before accepting a job. Very large playlists can still consume disk after acceptance, so monitor free space and avoid untrusted shared-tailnet access.
- Docker drops Linux capabilities, runs as your PUID/PGID, enforces memory/PID limits, uses a read-only root filesystem and writes only to the music and data mounts and temporary tmpfs. Preserve the loopback host port.
- Verify after deployment: `docker compose config`, `docker compose ps`, `docker compose logs --tail 50 spotdl-web`. From an allowed tailnet device the download page should work. A request directly to the loopback backend without the Tailscale header must be denied.
