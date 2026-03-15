# YouTube Transcript Downloader

YouTube csatornák és videók transzkriptjének letöltője. Directus backend, Astro + React frontend.

## Stack

- **Backend adatbázis/API:** Directus v11 (headless CMS) + PostgreSQL
- **Transcript fetcher:** Python FastAPI mikroszerviz (yt-dlp + youtube-transcript-api)
- **Frontend:** Astro v6 + React + TanStack Table
- **Infra:** Docker Compose

## Funkciók

- Csatornák hozzáadása: txt/csv fájl feltöltés, textarea, egyedi URL
- Egyedi videó hozzáadás YouTube linkkel
- Transzkript letöltés rate limitinggel (~60s/videó, randomizált)
- Napi automatikus csatorna-frissítés (új videók)
- Rendezhető táblázat: cím (link), feltöltés dátuma, hossz, státusz
- Transzkript megjelenítés modal ablakban
- Export: videónként, csatornánként, összesítve – TXT vagy MD formátum

## Gyors indítás

```bash
cp .env.example .env
# Szerkeszd a .env fájlt (jelszavak, token)
docker compose up -d
```

Szolgáltatások:
- **Frontend:** http://localhost:4321
- **Directus admin:** http://localhost:8055 (admin / .env ADMIN_PASSWORD)
- **Fetcher API:** http://localhost:8000

## .env változók

| Változó | Leírás |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL jelszó |
| `DIRECTUS_SECRET` | Directus titkos kulcs (JWT signing) |
| `DIRECTUS_ADMIN_EMAIL` | Admin e-mail |
| `DIRECTUS_ADMIN_PASSWORD` | Admin jelszó |
| `DIRECTUS_ADMIN_TOKEN` | Statikus API token (frontend + fetcher) |
| `PUBLIC_DIRECTUS_URL` | Directus URL a böngészőből (default: http://localhost:8055) |
| `PUBLIC_FETCHER_URL` | Fetcher URL a böngészőből (default: http://localhost:8000) |
| `REFRESH_CRON` | Napi frissítés cron (default: `0 2 * * *` = éjjel 2:00) |

## Csatorna feltöltési formátumok

**txt fájl** (soronként egy URL):
```
https://www.youtube.com/@channelname
@anotherhandle
UCxxxxxxxxxxxxxx
```

**csv fájl** (az URL-t tartalmazó oszlop automatikusan felismert):
```
name,url
Channel Name,https://www.youtube.com/@handle
```

## Rate limiting

- Transzkriptek között: 45-75 másodperc (véletlenszerű, átlag ~60s)
- Csatorna videólista lekérések között: 5-15 másodperc
- Soros feldolgozás (nincs párhuzamos letöltés)
- 429/403 hibára exponenciális backoff (max 120s)

## Architektúra

```
Frontend (Astro+React) ──► Directus REST API ──► PostgreSQL
         │
         └──► Fetcher (Python FastAPI)
                   │
                   ├─ yt-dlp (videólista, metaadat)
                   └─ youtube-transcript-api (transzkript)
```
