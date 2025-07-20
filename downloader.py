import os
import re
import requests
import subprocess
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, ID3NoHeaderError
from difflib import SequenceMatcher
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from datetime import datetime
from mutagen.id3 import ID3, TIT2, TPE1, TALB
from rapidfuzz import fuzz

LOG_FILE = "music_downloader.log"

# --- CONFIG ---
SPOTIFY_CLIENT_ID = "5b13bd39f5c346e6a65e9555404c66d4"
SPOTIFY_CLIENT_SECRET = "ac730118122842e7ae6fd9037adeefe4"

SPOTIFY_URLS = [
    "https://open.spotify.com/playlist/0dTxQ1v8wokOPLt7O0bo3p"
]

DOWNLOAD_DIR = "/mnt/user/Music"

JELLYFIN_SERVER = "http://192.168.86.32:8096"
JELLYFIN_USER = "colin"
JELLYFIN_PASS = "disuser"
JELLYFIN_PLAYLIST_NAME = "Bulk Music"
JELLYFIN_PLAYLIST_ID = "5a821269770c3d3e6e124b035348c396"

# --- HELPERS ---
def sanitize(text):
    sanitized_text = re.sub(r'[\\/*?:"<>|]', "-", text)
    sanitized_text = sanitized_text.rstrip('.')
    return sanitized_text

def spotify_client():
    credentials = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
    return spotipy.Spotify(client_credentials_manager=credentials)

def is_same_song(track, tag_artist, tag_title, tag_duration=None, duration_margin=5):

    def normalize(text):
        if not text:
            return ""
        text = text.lower()
        text = text.replace("_", " ")
        text = re.sub(r'\s*[\(\[].*?[\)\]]\s*', ' ', text)  # remove brackets (feat. info, etc.)
        text = re.sub(r'\b(feat|ft|featuring)\b\.?\s+\w+.*', '', text)  # remove "feat Artist"
        text = re.sub(r'[^a-z0-9\s]', '', text)  # remove punctuation
        return re.sub(r'\s+', ' ', text).strip()

    def has_modifier(text):
        modifiers = ['live', 'remix', 'edit', 'mix', 'bootleg', 'cover', 'instrumental', 'rework', 'version']
        text = text.lower()
        return any(mod in text for mod in modifiers)

    # Normalize inputs
    correct_title = normalize(track.get('title', ''))
    correct_artist = normalize(track.get('artist', ''))
    provided_title = normalize(tag_title)
    provided_artist = normalize(tag_artist)

    # Reject remixes, lives, etc.
    if has_modifier(tag_title) or has_modifier(tag_artist):
        return False

    # Fuzzy matching
    title_score = fuzz.token_set_ratio(correct_title, provided_title)
    artist_score = fuzz.token_set_ratio(correct_artist, provided_artist)

    if title_score < 60 or artist_score < 60:
        return False

    # Duration check
    correct_duration = track.get('duration')
    if correct_duration and tag_duration:
        if abs(correct_duration - tag_duration) > duration_margin:
            return False

    return True

# --- MAIN DOWNLOAD FUNCTION ---
def download_track(track):
    artist = sanitize(track["artist"])
    album = sanitize(track["album"])
    title = sanitize(track["title"])

    output_dir = Path(DOWNLOAD_DIR) / artist / album
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_path = output_dir / f"{title}.mp3"

    #✅ Check if file exists already
    if expected_path.exists() and expected_path.is_file() and expected_path.suffix.lower() == ".mp3":
        log(f"✅ Already exists: {expected_path}")
        if expected_path == '':
            log('Path is correct')
        return

    query = f"{title} {artist}"
    log(f"Trying SoundCloud: {query}")

    sc_command = [
        "scdl",
        "-s", query,
        "--path", str(output_dir),
        "--onlymp3",
        "--no-playlist"    
        ]

    try:
        subprocess.run(sc_command, check=True, timeout=60)

        #Find the newest .mp3 file in the folder
        mp3_files = list(output_dir.glob("*.mp3"))
        if not mp3_files:
            raise Exception("No MP3 downloaded from SoundCloud.")

        downloaded_file = max(mp3_files, key=os.path.getctime)

        try:
            audio = MP3(downloaded_file, ID3=ID3)
            duration = audio.info.length
            if duration < 60:
                log('Track not long enough')
                raise Exception("Too short")
            tag_artist = str(audio.get("TPE1", [None])[0])
            tag_title = str(audio.get("TIT2", [None])[0])

            if not is_same_song(track, tag_artist, tag_title, duration):
                raise Exception('Metadata not correct')
        except (ID3NoHeaderError, Exception) as e:
            log(f"⚠️ Metadata read failed: {e}")
            tag_artist, tag_title = "", ""

        #Fix metadata to match Spotify data
        try:
            if not audio.tags:
                audio.add_tags()
            audio["TIT2"] = TIT2(encoding=3, text=title)
            audio["TPE1"] = TPE1(encoding=3, text=artist)
            audio["TALB"] = TALB(encoding=3, text=album)
            audio.save()
        except Exception as e:
            log(f"⚠️ Failed to write ID3 tags: {e}")

        #  ^=^o  Rename to consistent name
        downloaded_file.rename(expected_path)
        log(f"✅ SoundCloud success: {expected_path}")
        return

    except Exception as e:
        log(f"⚠️ SoundCloud failed for {query}: {e}")

    #Fallback to spotDL
    log(f"Fallback to spotDL: {query}")
    spotdl_command = [
        "spotdl", query,
        "--output", f"{DOWNLOAD_DIR}/{artist}/{album}/{title}.{{output-ext}}",
        "--format", "mp3",
        "--bitrate", "320k"
    ]
    try:
        subprocess.run(spotdl_command, check=True, timeout=60)
        log(f"✅ spotDL success: {expected_path}")
    except subprocess.CalledProcessError:
        log(f"❌ spotDL failed for {query}")

# --- JELLYFIN UPDATE ---
def update_jellyfin_playlist():
    log("🔄 Updating Jellyfin...")
    auth_payload = {"Username": JELLYFIN_USER, "Pw": JELLYFIN_PASS}
    headers = {
        "Content-Type": "application/json",
        "Authorization": 'MediaBrowser Client="PythonApp", Device="PythonScript", DeviceId="script-01", Version="1.0.0"'
    }
    res = requests.post(f"{JELLYFIN_SERVER}/Users/AuthenticateByName", json=auth_payload, headers=headers)
    res.raise_for_status()
    data = res.json()
    token = data["AccessToken"]
    user_id = data["User"]["Id"]
    headers["X-MediaBrowser-Token"] = token

    # Refresh library
    log("📚 Triggering library scan...")
    requests.post(f"{JELLYFIN_SERVER}/Library/Refresh", headers=headers)

    # Fetch current music
    songs_res = requests.get(f"{JELLYFIN_SERVER}/Items?IncludeItemTypes=Audio&Recursive=true", headers=headers)
    library_songs = {item["Id"]: item["Name"] for item in songs_res.json().get("Items", [])}

    # Fetch playlist
    pl_res = requests.get(f"{JELLYFIN_SERVER}/Playlists/{JELLYFIN_PLAYLIST_ID}/Items", headers=headers)
    pl_ids = {item["Id"] for item in pl_res.json().get("Items", [])}

    # Add missing
    new_ids = [id_ for id_ in library_songs if id_ not in pl_ids]
    if new_ids:
        id_str = ",".join(new_ids)
        log(f"🎧 Adding {len(new_ids)} tracks to playlist...")
        requests.post(f"{JELLYFIN_SERVER}/Playlists/{JELLYFIN_PLAYLIST_ID}/Items?Ids={id_str}", headers=headers)
    else:
        log("✅ Playlist already up to date.")

def log(msg):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    with open(LOG_FILE, "a") as f:
        f.write(f"{timestamp} {msg}\n")
    print(msg)

def get_tracks(sp, url):
    playlist_id = url.split("/")[-1].split("?")[0]
    tracks = []
    offset = 0
    while True:
        results = sp.playlist_tracks(playlist_id, limit=100, offset=offset)
        for item in results["items"]:
            t = item["track"]
            if t:
                tracks.append({
                    "title": t["name"],
                    "artist": t["artists"][0]["name"],
                    "album": t["album"]["name"],
                    "duration": t["duration_ms"] // 1000
                })
        if results["next"] is None:
            break
        offset += 100
    return tracks

# --- MAIN ---
def main():
    sp = spotify_client()
    all_tracks = []

    for url in SPOTIFY_URLS:
        tracks = get_tracks(sp, url)
        log(f"📀 Found {len(tracks)} tracks in playlist.")
        all_tracks.extend(tracks)

    # Sequential download to avoid rate-limiting issues
    for track in all_tracks:
        try:
            download_track(track)
        except Exception as e:
            log(f"❌ Failed to download {track['title']} by {track['artist']}: {e}")

    update_jellyfin_playlist()
    log("🎉 All done!")


if __name__ == "__main__":
    main()