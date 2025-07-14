#!/usr/bin/env python3

import argparse
from downloader import spotify_client, download_track

def main():
    parser = argparse.ArgumentParser(description="Search Spotify and download the track using your existing script.")
    parser.add_argument("--query", "-q", required=True, help="Track title or title + artist")

    args = parser.parse_args()
    sp = spotify_client()

    results = sp.search(q=args.query, type="track", limit=1)
    if not results["tracks"]["items"]:
        print("❌ No results found.")
        return

    track = results["tracks"]["items"][0]

    print("\n🎧 Top Spotify Match:")
    print(f"  Title : {track['name']}")
    print(f"  Artist: {track['artists'][0]['name']}")
    print(f"  Album : {track['album']['name']}")
    print(f"  URL   : {track['external_urls']['spotify']}")

    confirm = input("\n✅ Download this track? (Y/n): ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("❌ Cancelled.")
        return

    # Convert to the expected format that your download_track() already uses:
    track_info = {
        "title": track["name"],
        "artist": track["artists"][0]["name"],
        "album": track["album"]["name"]
    }

    download_track(track_info)
    print("✅ Done!")

if __name__ == "__main__":
    main()
