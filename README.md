# YouTube Transcript Downloader

Helyi eszköz YouTube csatornák és videók feliratainak letöltésére és keresésére. Ha egy videónak nincs elérhető felirata, a Whisper.cpp speech-to-text modell automatikusan legenerálja.

## Stack

- **Frontend:** Astro + React, Caddy reverse proxy
- **Fetcher:** Python FastAPI – yt-dlp + youtube-transcript-api
- **Whisper:** Whisper.cpp (ggml-large-v3) – automatikus átírás
- **Adatbázis:** Directus v11 + PostgreSQL
- **AI jegyzetek:** Ollama chat API, alapértelmezetten `gemma4:31b-mlx-bf16`

## Indítás

```bash
cp .env.example .env
docker network create web
docker compose up
```

Böngészőben: **http://yt.test**

Ez a compose stack adja a közös helyi Caddy belépési pontot is. A Caddy a külső `web` Docker networkön keresztül proxyzza a `suliweb.test` domaint a `suliweb` repo konténerei felé (`suliweb-frontend`, `suliweb-backend`), ezért a `suliweb` stacknek is ugyanarra a `web` networkre kell csatlakoznia.

> **Első indításnál** a Whisper letölti a `ggml-large-v3.bin` modellt (~3 GB). Ez csak egyszer történik, a modell Docker volume-ban tárolódik.

## Előfeltételek

- Docker + Docker Compose
- dnsmasq a `*.test` domain helyi feloldásához
- `web` nevű külső Docker network
- mkcert tanúsítvány a `suliweb.test` HTTPS proxyhoz

### dnsmasq telepítés (Mac, egyszeri)

```bash
brew install dnsmasq
echo 'address=/.test/127.0.0.1' >> $(brew --prefix)/etc/dnsmasq.conf
sudo brew services start dnsmasq
sudo mkdir -p /etc/resolver
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/test
```

### Helyi TLS tanúsítvány `suliweb.test`-hez

```bash
brew install mkcert
mkcert -install
mkdir -p certs
mkcert -cert-file certs/suliweb.test.pem -key-file certs/suliweb.test-key.pem suliweb.test
```

A `certs/` könyvtár lokális titkokat tartalmaz, ezért nincs verziókezelve.

## Konfiguráció (.env)

| Változó | Leírás | Alapértelmezett |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL jelszó | `directus` |
| `DIRECTUS_ADMIN_TOKEN` | Directus admin token | `admin-token-change-me` |
| `REFRESH_CRON` | Csatornák automatikus frissítése | `0 7 * * *` |
| `SCHEDULER_TIMEZONE` | Automatikus frissítés időzónája | `Europe/Budapest` |
| `OLLAMA_BASE_URL` | Ollama chat API URL az AI jegyzetekhez | `http://host.docker.internal:11434` |
| `OLLAMA_CHAT_MODEL` | Ollama modell az AI jegyzetekhez | `gemma4:31b-mlx-bf16` |
| `AI_NOTES_AUTO` | Transzkript után automatikus AI jegyzet generálás | `true` |
| `AI_NOTES_BATCH_LIMIT` | Egyszerre generált hiányzó AI jegyzetek száma | `10` |
| `FETCH_WORKER_CONCURRENCY` | Fetch worker párhuzamosság | `1` |
| `AI_WORKER_CONCURRENCY` | AI worker párhuzamosság | `1` |
| `STALE_JOB_MINUTES` | Beragadt running job újrasorolása ennyi perc után | `30` |
| `JOB_CLEANUP_DAYS` | Befejezett/törölt jobok automatikus takarítása | `7` |
| `WHISPER_THREADS` | Whisper CPU szálak száma | `4` |
| `WHISPER_LANGUAGE` | Felismerési nyelv | `auto` |
| `WHISPER_BATCH_CRON` | Whisper batch futtatása | `0 3 * * *` |
| `WHISPER_BATCH_LIMIT` | Max videó egy batch-ben | `50` |

## Funkciók

- **Csatorna hozzáadása** – URL, `@handle`, vagy `.txt`/`.csv` fájl feltöltés
- **Egyedi videó hozzáadása** – csatorna automatikus felismerésével
- **Whisper átírás** – automatikus napi batch, vagy manuális indítás a headerből
- **Hiányzó dátumok frissítése** – feltöltési dátum pótlása yt-dlp-vel
- **Hiányzó transzkriptek újrapróbálása** – csatornafrissítéskor az új videók mellett a korábbi `pending`, `no_transcript` és `error` videók is újra sorra kerülnek
- **Végtelen scrollos videólista** – a lista 100-as adagokban tölt tovább, külön lapozó nélkül
- **Lebegő vissza a tetejére gomb** – hosszú listáknál jobb alul megjelenő nyíllal lehet a lista elejére ugrani
- **Keresés, rendezés és szűrés** – cím, dátum, hossz, transzkript státusz, AI jegyzet státusz és members-only jelölés szerint
- **Members-only videók kezelése** – yt-dlp metadata alapján `is_members_only` mezőbe kerülnek, a listában elrejthetők vagy külön kilistázhatók
- **Export** – videónként, csatornánként, összesítve – TXT, MD vagy Obsidian-kompatibilis MD formátum
- **Obsidian tudásgyűjtő export** – YAML frontmatter, YouTube forráslink, csatornatag, jegyzet szekció és kattintható időbélyeges transzkript
- **AI jegyzetek** – videónként generált összefoglaló, témák, tanulságok, kérdések, tanulási vázlat, kritika és Obsidian-kompatibilis jegyzet Ollamával
- **Külön AI feldolgozási sor** – az LLM jegyzetgenerálás egyedi `ai_note_video` jobokra bomlik, ezért nem blokkolja a videólista/frissítés/transzkript fetch folyamatot
- **Megbízható job queue** – dedupe kulcsok, retry, perzisztens progress, SQL lock alapú claim és több worker konténer
- **Admin és státusz nézet** – látszik a normál feldolgozási sor, az AI sor és az aktuálisan futó feladat; a futó vagy beragadt munkák leállíthatók
- **Napi automatikus frissítés** – új videók letöltése, alapból reggel 7-kor Europe/Budapest időzónában

## Videólista és szűrők

A fő videólista végtelen scrollt használ. A frontend 100-as adagokat kér le Directusból, alul automatikus betöltési ponttal és tartalék `További videók betöltése` gombbal. Hosszabb görgetés után jobb alul megjelenik egy lebegő felfelé nyíl, ami visszaugrik a lista tetejére.

Elérhető szűrők:

- cím keresés
- transzkript állapot: minden, kész, várakozik, nincs transzkript, hiba
- AI állapot: minden, kész, hiányzik, hiba
- members-only: mind, elrejtve, csak members

A members-only jelölés a `videos.is_members_only` mezőben tárolódik. Új videóknál a channel/video metadata lekéréskor töltődik. Régi videóknál csatornafrissítés vagy metadata backfill közben frissül, ezért egy régi adatbázisban kezdetben lehet, hogy még `0` members-only videó látszik.

## Obsidian export

Az `Obsidian` gomb olyan Markdown fájlt készít, amit közvetlenül be lehet húzni egy Obsidian vaultba. A videó note-ok tartalmaznak frontmattert (`type`, `source`, `title`, `channel`, `video_id`, `url`, `uploaded`, `duration`, `tags`), egy üres `Jegyzetek` részt, valamint időbélyeges transzkriptet. Az időbélyegek YouTube `t=` linkekre mutatnak, ezért Obsidianból vissza lehet ugrani a videó adott pontjára.

## AI jegyzet modell

Az AI jegyzeteket a fetcher Ollamán keresztül generálja. A használt modell az `.env` fájlban állítható:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=gemma4:31b-mlx-bf16
```

Modellcsere után indítsd újra a fetchert és az AI workert:

```bash
docker compose up -d fetcher ai-worker
```

Az AI jegyzetek külön háttérsoron futnak. A transzkript letöltése után a videó csak bekerül az AI sorba, ezért a fetcher tovább tud dolgozni a következő videókon. A globális AI backfill sok kis `ai_note_video` jobra bomlik, így a folyamat deduplikálható, újrapróbálható és pontos progresszt tud mutatni. A frontend státuszsávja külön mutatja a normál sort és az `AI sor` állapotát; a `Stop` gomb mindkét sort leállítja és kiüríti.

Az AI jegyzetgenerálás angol munkanyelvű: a `summary`, `topics`, `takeaways`, `questions`, `obsidian_note`, `study_guide` és `critique` mezők angolul készülnek akkor is, ha a videó transzkriptje más nyelvű. Az egyes mezők külön is újragenerálhatók.

Az admin felület a feldolgozási sort Directus `jobs` collectionben kezeli. A sor így látható és szerkeszthető: queued/paused/running/error/cancelled állapot, sorrend módosítás, pause/resume, azonnali indítás és törlés.

## Job queue és worker modell

A fetcher API és a workerek külön konténerekben futnak:

- `fetcher` – FastAPI, scheduler, státusz és enqueue végpontok
- `fetch-worker` – csatornafrissítés, metadata pótlás, transzkript letöltés
- `ai-worker` – AI jegyzetgenerálás
- `whisper` – speech-to-text fallback

A `jobs` collection tartalmazza a dedupe kulcsot, retry/progress mezőket, lock adatokat és hibákat. A worker SQL lock alapú claimet használ, így ugyanazt a jobot több worker nem veszi fel egyszerre. A `FETCH_WORKER_CONCURRENCY` és `AI_WORKER_CONCURRENCY` változókkal csak ott érdemes növelni a párhuzamosságot, ahol a rate limit és az LLM kapacitás engedi.

A csatornafrissítés transzkript szempontból önálló: metadata backfill, members-only jelölés vagy AI jegyzet enqueue hiba nem állítja meg a többi videó transzkript letöltését. Egy videó hibája `error` státuszba kerülhet, de a csatorna többi videója tovább feldolgozódik.

## Adatbázis és indexek

A bootstrap a szükséges mezőket és indexeket automatikusan létrehozza. Fontosabb videómezők:

- `uploaded_at`
- `channel_id`
- `thumbnail_url`
- `is_members_only`
- `ai_notes_status`
- `summary`

Fontosabb indexek:

- `idx_videos_uploaded_at`
- `idx_videos_channel_id`
- `idx_videos_members_only`
- `idx_videos_ai_notes_status`
- `idx_videos_summary_missing`
- `idx_videos_thumbnail_missing`
- `idx_jobs_queue_status_sort`
- `idx_jobs_dedupe_active`

## Rate limiting

- Transzkriptek között: 45–75 másodperc (véletlenszerű)
- Csatorna videólista lekérések között: 5–15 másodperc
- Alapértelmezetten 1 fetch worker és 1 AI worker fut; a párhuzamosság konfigurálható, de YouTube/LLM rate limit miatt óvatosan növeld

## Architektúra

```
http://yt.test
      │
   Caddy ──► Frontend (Astro+React, :4321)
                  │  Vite proxy
                  ├─ /admin  ──► Directus (:8055) ──► PostgreSQL
                  ├─ /api    ──► Fetcher API (:8000)
                  └─ /whisper──► Whisper (:8001)

Fetcher API ──► Directus jobs ──► fetch-worker / ai-worker
```
