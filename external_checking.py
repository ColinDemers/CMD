import os
from mutagen.mp3 import MP3
import downloader
import search

def main(dire):
    for dirpath, dirnames, filenames in os.walk(dire):
        for filename in filenames:
            if filename.lower().endswith('.mp3'):
                file_path = os.path.join(dirpath, filename)
                try:
                    audio = MP3(file_path)
                    duration = audio.info.length
                    if duration < 60:
                        print(f"Deleting {file_path}: {duration:.2f} seconds")
                        os.remove(file_path)

                        path_parts = file_path.split(os.sep)
                        artist = path_parts[-2]
                        album = path_parts[-1]
                        track = os.path.splitext(album)[0]

                        track = search.search(f"{track} {artist}")
                        downloader.download_track(track)
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")

main(downloader.DOWNLOAD_DIR)
