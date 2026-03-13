import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import time
import os

CHANNEL_NAME = "christianlempa"

CHANNEL_URL = f"https://www.youtube.com/@{CHANNEL_NAME}/videos"
OUTPUT_FILE = f"{CHANNEL_NAME}_all_transcripts.txt"

# 1. Összes videó ID lekérése
print("Videó ID-k gyűjtése...")
ydl_opts = {
    'extract_flat': True,
    'quiet': True,
    'ignoreerrors': True,
}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(CHANNEL_URL, download=False)
    videos = [(e['id'], e.get('title', 'Ismeretlen cím')) 
              for e in info['entries'] if e and e.get('id')]

print(f"{len(videos)} videó találva.")

# 2. Már kész videók kihagyása
already_done = set()
if os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as existing:
        for line in existing:
            if line.startswith("URL: https://www.youtube.com/watch?v="):
                already_done.add(line.strip().split("v=")[1])
    print(f"{len(already_done)} videó már kész, kihagyva.")

# 3. Transzkriptek letöltése
ytt_api = YouTubeTranscriptApi()

with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
    for i, (video_id, title) in enumerate(videos, 1):
        if video_id in already_done:
            print(f"[{i}/{len(videos)}] ⏭️ Kihagyva: {title}")
            continue

        url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[{i}/{len(videos)}] {title}")
        
        try:
            transcript_list = ytt_api.list(video_id)
            try:
                transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
            except:
                transcript = next(iter(transcript_list))
            
            fetched = transcript.fetch()
            text = ' '.join([s.text for s in fetched])
            
            f.write(f"=== {title} ===\n")
            f.write(f"URL: {url}\n\n")
            f.write(text + "\n\n")
            
        except Exception as e:
            print(f"  ⚠️ Hiba: {e}")
            f.write(f"=== {title} ===\n")
            f.write(f"URL: {url}\n")
            f.write("[Felirat nem elérhető]\n\n")
        
        time.sleep(60)

print(f"\n✅ Kész! Mentve: {OUTPUT_FILE}")