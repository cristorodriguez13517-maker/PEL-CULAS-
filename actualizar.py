
import os
import re
import json
import time
import requests
import unicodedata
from difflib import SequenceMatcher

# ==================================================
# CONFIGURACIÓN
# ==================================================

YOUTUBE_KEY = os.environ["YOUTUBE_API_KEY"]
TMDB_KEY = os.environ["TMDB_API_KEY"]

PLAYLIST_ID = "PLaQN5GT3v1ko"

YOUTUBE_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

session = requests.Session()


# ==================================================
# PETICIONES A LAS API
# ==================================================

def api_get(url, params):
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


# ==================================================
# OBTENER LOS VÍDEOS DE LA LISTA DE YOUTUBE
# ==================================================

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

        data = api_get(YOUTUBE_URL, params)

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            resource = snippet.get("resourceId", {})
            video_id = resource.get("videoId")

            if not video_id:
                continue

            title = snippet.get("title", "").strip()

            # Saltar vídeos privados o eliminados
            if title.lower() in (
                "private video",
                "deleted video",
                "vídeo privado",
                "video privado",
                "vídeo eliminado",
                "video eliminado"
            ):
                continue

            videos.append({
                "youtube_id": video_id,
                "youtube_title": title,
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", "")
            })

        page_token = data.get("nextPageToken")

        if not page_token:
            break

    return videos


# ==================================================
# LIMPIAR Y NORMALIZAR TÍTULOS
# ==================================================

def clean_title(title):
    title = re.sub(
        r"\s*[\[(](?:oficial|official trailer|trailer oficial|"
        r"tráiler oficial|película completa|pelicula completa|"
        r"full movie|4k|2160p|1080p|720p)[^\])]*[\])]\s*",
        " ",
        title,
        flags=re.IGNORECASE
    )

    title = re.sub(r"\s+", " ", title).strip()
    return title


def normalize(text):
    text = (text or "").lower().strip()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# ==================================================
# DETECTAR CALIDAD DESDE EL TÍTULO/DESCRIPCIÓN
# ==================================================

def detect_quality(title, description):
    text = f"{title} {description}".lower()

    if re.search(r"\b(4k|2160p|uhd)\b", text):
        return "4K"

    if re.search(r"\b(fhd|1080p|full hd)\b", text):
        return "FHD"

    if re.search(r"\b(hd|720p)\b", text):
        return "HD"

    return ""


# ==================================================
# BUSCAR LA PELÍCULA CORRECTA EN TMDB
# ==================================================

def find_tmdb_movie(title):
    original_title = clean_title(title)

    year_match = re.search(
        r"\b(19\d{2}|20\d{2})\b",
        original_title
    )
    year = year_match.group(1) if year_match else None

    query = re.sub(
        r"\s*[\(\[]?(19\d{2}|20\d{2})[\)\]]?\s*",
        " ",
        original_title
    )
    query = re.sub(r"\s+", " ", query).strip()

    if not query:
        query = original_title

    wanted = normalize(query)
    candidates_by_id = {}

    # Probar español e inglés, con y sin año
    for language in ("es-ES", "en-US"):
        searches = [True, False] if year else [False]

        for use_year in searches:
            params = {
                "api_key": TMDB_KEY,
                "language": language,
                "query": query,
                "include_adult": "false",
                "page": 1
            }

            if use_year and year:
                params["year"] = year

            data = api_get(TMDB_SEARCH_URL, params)

            for movie in data.get("results", []):
                movie_id = movie.get("id")

                if not movie_id:
                    continue

                previous = candidates_by_id.get(movie_id)

                if previous is None:
                    candidates_by_id[movie_id] = movie
                else:
                    # Preferir el resultado que tenga más información
                    if (
                        not previous.get("poster_path")
                        and movie.get("poster_path")
                    ):
                        candidates_by_id[movie_id] = movie

            time.sleep(0.05)

    if not candidates_by_id:
        print(f"TMDB: no hay resultados para '{title}'")
        return None

    best_movie = None
    best_score = -1

    for movie in candidates_by_id.values():
        names = [
            movie.get("title", ""),
            movie.get("original_title", "")
        ]

        name_score = max(
            (
                SequenceMatcher(
                    None,
                    wanted,
                    normalize(name)
                ).ratio()
                for name in names
                if name
            ),
            default=0
        )

        release_date = movie.get("release_date", "")
        score = name_score

        if year:
            if release_date.startswith(year):
                score += 0.20
            elif release_date and re.match(r"\d{4}", release_date):
                score -= 0.15

        if score > best_score:
            best_score = score
            best_movie = movie

    # Evitar asignar películas con títulos poco parecidos
    if not best_movie or best_score < 0.72:
        print(
            f"TMDB: coincidencia insuficiente para '{title}'. "
            f"Mejor puntuación: {best_score:.2f}"
        )
        return None

    print(
        f"TMDB: '{title}' -> "
        f"'{best_movie.get('title')}' "
        f"(ID {best_movie.get('id')})"
    )

    return best_movie


# ==================================================
# OBTENER DETALLES, GÉNEROS Y DURACIÓN
# ==================================================

def get_movie_details(movie_id):
    params = {
        "api_key": TMDB_KEY,
        "language": "es-ES"
    }

    return api_get(
        f"{TMDB_MOVIE_URL}/{movie_id}",
        params
    )


# ==================================================
# OBTENER EL LOGO OFICIAL DE LA PELÍCULA
# ==================================================

def get_movie_logo(movie_id):
    params = {
        "api_key": TMDB_KEY,
        "include_image_language": "es,en,null"
    }

    try:
        data = api_get(
            f"{TMDB_MOVIE_URL}/{movie_id}/images",
            params
        )
    except requests.RequestException as error:
        print(f"No se pudieron cargar los logos de {movie_id}: {error}")
        return None

    logos = data.get("logos", [])

    if not logos:
        return None

    # Preferencia: español, inglés y después cualquier idioma
    for language in ("es", "en", None):
        for logo in logos:
            if logo.get("iso_639_1") == language and logo.get("file_path"):
                return IMAGE_BASE + "w780" + logo["file_path"]

    # Si no hay un logo en esos idiomas, usar el primero disponible
    for logo in logos:
        if logo.get("file_path"):
            return IMAGE_BASE + "w780" + logo["file_path"]

    return None


# ==================================================
# CONSTRUIR EL CATÁLOGO
# ==================================================

def main():
    if not PLAYLIST_ID or "PEGA_AQUI" in PLAYLIST_ID:
        raise SystemExit(
            "Configura PLAYLIST_ID en actualizar.py."
        )

    videos = get_youtube_videos()

    print(f"VÍDEOS ENCONTRADOS EN YOUTUBE: {len(videos)}")

    catalog = []

    for index, video in enumerate(videos, start=1):
        youtube_title = video["youtube_title"]
        description = video["description"]
        video_id = video["youtube_id"]

        print(
            f"\n[{index}/{len(videos)}] "
            f"Procesando: {youtube_title}"
        )

        quality = detect_quality(youtube_title, description)

        entry = {
            **video,
            "title": youtube_title,
            "tmdb_id": None,
            "poster": None,
            "logo": None,
            "backdrop": None,
            "overview": "",
            "release_date": "",
            "runtime": None,
            "genres": [],
            "quality": quality,
            "match_status": "pendiente",
            "youtube_url": (
                "https://www.youtube.com/watch?v=" + video_id
            )
        }

        try:
            movie = find_tmdb_movie(youtube_title)

            if movie:
                movie_id = movie.get("id")
                details = get_movie_details(movie_id)

                poster_path = (
                    details.get("poster_path")
                    or movie.get("poster_path")
                )

                backdrop_path = (
                    details.get("backdrop_path")
                    or movie.get("backdrop_path")
                )

                # Utilizar los datos de TMDB cuando haya coincidencia
                entry.update({
                    "title": (
                        details.get("title")
                        or movie.get("title")
                        or youtube_title
                    ),
                    "tmdb_id": movie_id,
                    "poster": (
                        IMAGE_BASE + "w780" + poster_path
                        if poster_path else None
                    ),
                    "backdrop": (
                        IMAGE_BASE + "original" + backdrop_path
                        if backdrop_path else None
                    ),
                    "overview": details.get("overview", ""),
                    "release_date": (
                        details.get("release_date")
                        or movie.get("release_date", "")
                    ),
                    "runtime": details.get("runtime"),
                    "genres": [
                        genre.get("name")
                        for genre in details.get("genres", [])
                        if genre.get("name")
                    ],
                    "match_status": "encontrada"
                })

                # El logo se consulta por separado
                entry["logo"] = get_movie_logo(movie_id)

                print(
                    "Carátula:",
                    "OK" if entry["poster"] else "No disponible"
                )
                print(
                    "Banner:",
                    "OK" if entry["backdrop"] else "No disponible"
                )
                print(
                    "Logo:",
                    "OK" if entry["logo"] else "No disponible"
                )

        except requests.RequestException as error:
            print(
                f"Error de API procesando '{youtube_title}': {error}"
            )
            entry["match_status"] = "error_api"

        catalog.append(entry)

        # Pausa pequeña para no hacer peticiones demasiado seguidas
        time.sleep(0.15)

    with open("peliculas.json", "w", encoding="utf-8") as file:
        json.dump(
            catalog,
            file,
            ensure_ascii=False,
            indent=2
        )

    matched = sum(
        1 for item in catalog
        if item["match_status"] == "encontrada"
    )

    print("\n===================================")
    print(f"Vídeos procesados: {len(catalog)}")
    print(f"Películas encontradas en TMDB: {matched}")
    print(f"Pendientes/error: {len(catalog) - matched}")
    print("Archivo generado: peliculas.json")
    print("===================================")


if __name__ == "__main__":
    main()
