# YouTube Transcript Downloader

Helyi eszköz YouTube csatornák és videók feliratainak letöltésére és keresésére. Ha egy videónak nincs elérhető felirata, a Whisper.cpp speech-to-text modell automatikusan legenerálja.

## Stack

- **Frontend:** Astro + React, Caddy reverse proxy
- **Fetcher:** Python FastAPI – yt-dlp + youtube-transcript-api
- **Whisper:** Whisper.cpp (ggml-large-v3) – automatikus átírás
- **Adatbázis:** Directus v11 + PostgreSQL

## Indítás

```bash
cp .env.example .env
docker compose up
```

Böngészőben: **http://yt.test**

> **Első indításnál** a Whisper letölti a `ggml-large-v3.bin` modellt (~3 GB). Ez csak egyszer történik, a modell Docker volume-ban tárolódik.

## Előfeltételek

- Docker + Docker Compose
- dnsmasq a `*.test` domain helyi feloldásához

### dnsmasq telepítés (Mac, egyszeri)

```bash
brew install dnsmasq
echo 'address=/.test/127.0.0.1' >> $(brew --prefix)/etc/dnsmasq.conf
sudo brew services start dnsmasq
sudo mkdir -p /etc/resolver
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/test
```

## Konfiguráció (.env)

| Változó | Leírás | Alapértelmezett |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL jelszó | `directus` |
| `DIRECTUS_ADMIN_TOKEN` | Directus admin token | `admin-token-change-me` |
| `REFRESH_CRON` | Csatornák automatikus frissítése | `0 2 * * *` |
| `WHISPER_THREADS` | Whisper CPU szálak száma | `4` |
| `WHISPER_LANGUAGE` | Felismerési nyelv | `auto` |
| `WHISPER_BATCH_CRON` | Whisper batch futtatása | `0 3 * * *` |
| `WHISPER_BATCH_LIMIT` | Max videó egy batch-ben | `50` |

## Funkciók

- **Csatorna hozzáadása** – URL, `@handle`, vagy `.txt`/`.csv` fájl feltöltés
- **Egyedi videó hozzáadása** – csatorna automatikus felismerésével
- **Whisper átírás** – automatikus napi batch, vagy manuális indítás a headerből
- **Hiányzó dátumok frissítése** – feltöltési dátum pótlása yt-dlp-vel
- **Keresés és rendezés** – cím, dátum, hossz, státusz szerint
- **Export** – videónként, csatornánként, összesítve – TXT vagy MD formátum
- **Napi automatikus frissítés** – új videók letöltése (hajnali 2)

## Rate limiting

- Transzkriptek között: 45–75 másodperc (véletlenszerű)
- Csatorna videólista lekérések között: 5–15 másodperc
- Soros feldolgozás (nincs párhuzamos letöltés)

## Architektúra

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React, :4321)
                  │  Vite proxy
                  ├─ /admin  ──► Directus (:8055) ──► PostgreSQL
                  ├─ /api    ──► Fetcher (:8000)
                  └─ /whisper──► Whisper (:8001)
```
