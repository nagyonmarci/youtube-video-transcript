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
| `OLLAMA_CHAT_MODEL` | Ollama modell az AI jegyzetekhez | `gemma4:31b` |
| `AI_NOTES_AUTO` | Transzkript után automatikus AI jegyzet generálás | `true` |
| `AI_NOTES_BATCH_LIMIT` | Egyszerre generált hiányzó AI jegyzetek száma | `10` |
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
- **Export** – videónként, csatornánként, összesítve – TXT, MD vagy Obsidian-kompatibilis MD formátum
- **Obsidian tudásgyűjtő export** – YAML frontmatter, YouTube forráslink, csatornatag, jegyzet szekció és kattintható időbélyeges transzkript
- **AI jegyzetek** – videónként generált összefoglaló, témák, tanulságok, kérdések és Obsidian-kompatibilis jegyzet Ollamával
- **Külön AI feldolgozási sor** – az LLM jegyzetgenerálás nem blokkolja a videólista/frissítés/transzkript fetch folyamatot
- **Admin és státusz nézet** – látszik a normál feldolgozási sor, az AI sor és az aktuálisan futó feladat; a futó vagy beragadt munkák leállíthatók
- **Napi automatikus frissítés** – új videók letöltése, alapból reggel 7-kor Europe/Budapest időzónában

## Obsidian export

Az `Obsidian` gomb olyan Markdown fájlt készít, amit közvetlenül be lehet húzni egy Obsidian vaultba. A videó note-ok tartalmaznak frontmattert (`type`, `source`, `title`, `channel`, `video_id`, `url`, `uploaded`, `duration`, `tags`), egy üres `Jegyzetek` részt, valamint időbélyeges transzkriptet. Az időbélyegek YouTube `t=` linkekre mutatnak, ezért Obsidianból vissza lehet ugrani a videó adott pontjára.

## AI jegyzet modell

Az AI jegyzeteket a fetcher Ollamán keresztül generálja. A használt modell az `.env` fájlban állítható:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=gemma4:31b
```

Modellcsere után indítsd újra a fetchert:

```bash
docker compose up -d fetcher
```

Az AI jegyzetek külön háttérsoron futnak. A transzkript letöltése után a videó csak bekerül az AI sorba, ezért a fetcher tovább tud dolgozni a következő videókon. A frontend státuszsávja külön mutatja a normál sort és az `AI sor` állapotát; a `Stop` gomb mindkét sort leállítja és kiüríti.

Az AI jegyzetgenerálás angol munkanyelvű: a `summary`, `topics`, `takeaways`, `questions` és `obsidian_note` mezők angolul készülnek akkor is, ha a videó transzkriptje más nyelvű.

Az admin felület a feldolgozási sort Directus `jobs` collectionben kezeli. A sor így látható és szerkeszthető: queued/paused/running/error/cancelled állapot, sorrend módosítás, pause/resume, azonnali indítás és törlés.

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
