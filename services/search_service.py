"""
services/search_service.py — Mixtape

Handles song search logic.
"""

from app import db
from models import Song, Tag, song_tags


def search_songs(query: str) -> list[dict]:
    """
    Search for songs by title or artist name.

    Returns all songs where the title or artist contains the query string
    (case-insensitive), along with their associated tags.

    Args:
        query: The search string to match against title and artist fields.

    Returns:
        A list of song dicts. Each dict includes all song fields plus a
        'tags' list of tag name strings. If multiple users have shared the
        same song (identical title and artist), only one entry is returned.
    """
    results = (
        db.session.query(Song)
        .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(
            db.or_(
                Song.title.ilike(f"%{query}%"),
                Song.artist.ilike(f"%{query}%"),
            )
        )
        .all()
    )

    seen = set()
    deduped = []
    for song in results:
        key = (song.title.lower(), song.artist.lower())
        if key not in seen:
            seen.add(key)
            deduped.append(song)

    return [song.to_dict() for song in deduped]


def get_song(song_id: str) -> dict:
    """
    Get a single song by ID.

    Args:
        song_id: The UUID of the song.

    Returns:
        A song dict, or raises ValueError if not found.
    """
    song = db.session.get(Song, song_id)
    if not song:
        raise ValueError(f"Song {song_id} not found")
    return song.to_dict()
