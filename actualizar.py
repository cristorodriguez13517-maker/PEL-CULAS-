import os
import re
import json
import time
import requests
from difflib import SequenceMatcher

YOUTUBE_KEY = os.environ["YOUTUBE_API_KEY"]
TMDB_KEY = os.environ["TMDB_API_KEY"]

# Sustituye este texto por el ID real de tu lista de películas.
PLAYLIST_ID = "PLaQN5GT3v1ko"

YOUTUBE_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
TMDB_URL = "https://api.themoviedb.org/3/search/movie"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

def get_youtube_videos():
    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": PLAYLIST_ID,
            "maxResults": 50,
            "key": YOUTUBE_KEY
        }

        if page_token:
            params["pageToken"] = page_token

        response = requests.get(
            YOUTUBE_URL, params=params, timeout=30
        )
        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = (
                snippet.get("resourceId", {}).get("videoId")
            )

            if not video_id or snippet.get("title") == "Private video":
                continue

            videos.append({
                "youtube_id": video_id,
                "youtube_title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", "")
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos


def clean_title(title):
    # Elimina algunos sufijos habituales, sin alterar el original.
    title = re.sub(
        r"\s*[\[(](oficial|official trailer|trailer oficial|"
        r"película completa|pelicula completa)[^\])]*[\])]\s*",
        " ",
        title,
        flags=re.IGNORECASE
    )
    title = re.sub(r"\s+", " ", title).strip()
    return title


def normalize(text):
    text = text.lower()
    text = re.sub(r"\(\d{4}\)", " ", text)
    text = re.sub(r"[^a-z0-9áéíóúüñ ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_tmdb_movie(title):
    params = {
        "api_key": TMDB_KEY,
        "language": "es-ES",
        "query": clean_title(title),
        "include_adult": "false"
    }

    response = requests.get(
        TMDB_URL, params=params, timeout=30
    )
    response.raise_for_status()

    results = response.json().get("results", [])
    if not results:
        return None

    wanted = normalize(clean_title(title))
    best = None
    best_score = 0

    for movie in results:
        candidates = [
            movie.get("title", ""),
            movie.get("original_title", "")
        ]

        score = max(
            SequenceMatcher(None, wanted, normalize(candidate)).ratio()
            for candidate in candidates if candidate
        ) if any(candidates) else 0

        if score > best_score:
            best_score = score
            best = movie

    # Evita asignar datos automáticamente si no hay
    # una coincidencia suficientemente fiable.
    if not best or best_score < 0.72:
        return None

    return best


def main():
    if "PEGA_AQUI" in PLAYLIST_ID:
        raise SystemExit(
            "Configura PLAYLIST_ID en actualizar.py antes de continuar."
        )

    videos = get_youtube_videos()
    catalog = []

    for video in videos:
        title = video["youtube_title"]
        movie = find_tmdb_movie(title)

        entry = {
            **video,
            "title": title,
            "tmdb_id": None,
            "poster": None,
            "backdrop": None,
            "overview": "",
            "release_date": "",
            "match_status": "pendiente",
            "youtube_url": (
                "https://www.youtube.com/watch?v="
                + video["youtube_id"]
            )
        }

        if movie:
            entry.update({
                "tmdb_id": movie.get("id"),
                "poster": (
                    IMAGE_BASE + "w500" + movie["poster_path"]
                    if movie.get("poster_path") else None
                ),
                "backdrop": (
                    IMAGE_BASE + "original" + movie["backdrop_path"]
                    if movie.get("backdrop_path") else None
                ),
                "overview": movie.get("overview", ""),
                "release_date": movie.get("release_date", ""),
                "match_status": "revisar"
            })

        catalog.append(entry)
        time.sleep(0.05)

    with open("peliculas.json", "w", encoding="utf-8") as file:
        json.dump(catalog, file, ensure_ascii=False, indent=2)

    print(f"Catálogo generado: {len(catalog)} vídeos.")


if __name__ == "__main__":
    main()
