# Project 5 - Mixtape Bug Hunt

---

## Codebase Map

### Main Directories and Notes

- `models.py` - Defines 5 SQLAlchemy models: User, Song, Playlist, PlaylistSong, and Notification.
  - Association tables
    - `friendships`
      - Modeled with only one row direction, so logic else where much check both directions or both rows are inserted when a friend request is made. (Changed with A.friends returns [B] but B.friends returns []) (Realized friends are just seeded not actually a feature to add a friend)
    - `playlist_entries`
      - Has "position" and "added_by" foreign keys but doesn't get populated by the songs relationship in "Playlist" class.
  - `User`
    - Only returns friends where the use is `user_id`
    - No email validation at the model layer, so should be enforced elsewhere
  - `Song`
    - `album` / `genre` are nullable but `to_dict()` passes None
  - `Rating`
    - `UniqueConstraint(user_id, song_id)` is one rating per user per song, so "update rating" logic would need to be upsert or IntegrityError will be thrown.
    - `score` has no `CheckConstraint` enforcing 1-5 like the comment says. Range is convention but not enforced.
- `./routes`
  - `users.py` - Holds routes related to specific user interactions like getting a user, their streaks, and checking and reading notifications.
  - `songs.py` - Holds routes related to song interactions like searching a song and its details, listening, and rating a track.
  - `playlists.py` - Holds routes realted to playlist interactions like creating and viewing a playlist's details getting song count, and adding songs to a playlist.
  - `feed.py` - Holds routes related to the social aspects of the service like seeing who has listened recently and viewing all friends listening activity.
- `./services` - Has the main functions to complete the interactions specified in the routes.

### Sample Data Flow Trace

Here is a the data flow for creating a playlist and adding a song to that playlist:

1. `POST /` routes/playlists.py:create
   - Takes a JSON body `{name, created_by, is_collaborative` from request and calls `create_playlist(name, created_by, is_collaborative)` in `services/playlist_service.py`
2. `create_playlist(name: str, created_by_user_id: str, is_collaborative: bool = True)` -> Playlist
   - Looks up `User` by id, builds and committes a new Playlist row, return the `Playlist` model instance and `playlist.todict()` is serialized and return as JSON
3. `POST /<playlist_id>/songs`
   - Takes a JSON body `{song_id, added_by}`, plus `playlist_id` from the URL and calls `add_to_playlist(playlist_id, song_id, added_by)` (this comes from `notication_service` not `playlist_service`)
4. `add_to_playlist(playlist_id, song_id, added_by_user_id)` -> None
   - Looks up `Song`, `User`, and `Playlist` and if the song isn't in `playlist.songs` is appends it via `playlist.songs.append(song)` and commits. It also calls `create_notification` on the side if the song's original sharer is not the adder. Returns `None`

### Patterns

All routes commit directly to service functions and are organized by what these functions interact with primarily.

---

## Bug Fix #1

### Issue Number and Title

**Issue 1: My listening streak keeps resetting**

### Reproducing the Bug

I ran `pytest tests/test_Streaks.py -v` and looked at the `streak_increments_on_sunday` test which starts as treak on Saturday and tries to update it on Sunday and this test fails. The streak stays at 1 instead of updating to 2.

### Finding Root

I traced the data flow from the `/user` route to the `get_streak()` function in the `streak_service`. From there, I saw it returns `user.listen_streak` so I checked to see where else that field gets updated and saw it was in `update_listening_streak` function. Once I saw this was the only function that actually modifies that field, I knew I was in the right place.

### Root Cause

The actual line that updates the streak by 1, `user.listening_streak += 1` is inside an elif that checks if the last day a user listened was only one day ago AND that the current day of the week is not Sunday, `elif days_since_last == 1 and today.weekday() != 6`. This AND will cause this elif to evaluate to False every Sunday, leading the code to default to the else clause that resets the listening streak to 1, `user.listening_streak = 1`.

### Fix and Side-Effect Check

The fix was to just remove that AND clause from the elif and leave it just as `elif days_since_last == 1`, since the function docstring says nothing about any different functionality or exceptions on Sunday. I checked to make sure streaks still increment on all other days and that it still gets set to 1 for a new user or a skipped day.
