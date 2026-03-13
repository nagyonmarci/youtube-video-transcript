# YouTube Transcript Manager

YouTube csatornák videóinak automatikus transcript letöltése, kezelése és exportálása.

## Jelenlegi stack

- **Backend:** FastAPI + asyncpg + yt-dlp + youtube-transcript-api
- **Frontend:** Astro + React
- **DB:** PostgreSQL
- **Infra:** Docker Compose

## Funkciók

- Google OAuth bejelentkezés
- YouTube csatornák hozzáadása (per user)
- Automatikus transcript letöltés (youtube-transcript-api + yt-dlp fallback)
- YouTube cookie támogatás (bot-védelem megkerülése)
- Videó lista + transcript megtekintés
- Export txt/md formátumban
- Google Drive-ba mentés
- Background worker queue (soros feldolgozás, rate limiting)

## Futtatás

```bash
cp .env.example .env  # kitölteni a változókat
docker compose up -d
```

- API: http://localhost:8000
- Frontend: http://localhost:4321
- DB: localhost:5432

## Lehetséges jövőbeli architektúra: Directus + Astro

A jelenlegi custom FastAPI backend nagyrésze kiváltható lenne Directus-szal:

### Amit a Directus kiváltana

| Jelenlegi custom kód | Directus |
|---|---|
| `auth.py` – Google OAuth, JWT, user CRUD | Beépített auth (Google OAuth SSO) |
| `init.sql` – kézi DB séma | Admin UI-ból kezelhető séma |
| `channels.py` – CRUD endpointok | Auto-generált REST + GraphQL API |
| `videos.py` – listázás, szűrés | Beépített szűrés, rendezés, pagination |
| `schemas.py` – Pydantic modellek | Nem kell |
| `database.py` – connection pool | Beépített |
| Admin felület | Teljes admin panel |

### Ami custom maradna

- **Worker logika** (yt-dlp + transcript letöltés) – Directus Flow/Hook-ként vagy külső Python service-ként
- **Google Drive export** – Directus Flow-ként megoldható
- **Cookie kezelés** – custom extension

### Tervezett architektúra

```
Astro frontend  -->  Directus (auth + API + DB)  -->  PostgreSQL
                          |
                     Directus Flow / külső worker
                          |
                     yt-dlp + youtube-transcript-api
```

### Előnyök

- ~60-70% kevesebb custom kód
- Beépített admin panel a tartalom kezeléséhez
- Granulált jogosultságkezelés
- Auto-generált API dokumentáció
- Egyszerűbb maintenance

### Hátrányok

- Directus container extra resource igény
- Directus Flows Node.js-ben futnak (a worker logika Python – vagy át kell írni JS-re, vagy külön service marad)
- Kevesebb kontroll az API felett
