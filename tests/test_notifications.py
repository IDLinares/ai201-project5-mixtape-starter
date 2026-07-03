"""
tests/test_notifications.py — Mixtape

Tests for notification creation logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, playlist_entries, friendships
from services.notification_service import rate_song, add_to_playlist, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_users_and_song(app):
    """
    User A and User B are friends. User A shares a song.
    """
    with app.app_context():
        user_a = User(username="user_a", email="a@example.com")
        user_b = User(username="user_b", email="b@example.com")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=user_b.id))
        db.session.execute(friendships.insert().values(user_id=user_b.id, friend_id=user_a.id))

        song = Song(title="Shared Song", artist="Some Artist", shared_by=user_a.id)
        db.session.add(song)
        db.session.commit()

        yield {"user_a": user_a, "user_b": user_b, "song": song}


def test_rating_a_friends_song_notifies_the_sharer(app, seed_users_and_song):
    """
    When User B rates a song shared by User A, User A should receive a
    notification about it (mirroring how add_to_playlist notifies the
    sharer when a friend adds their song to a playlist).
    """
    with app.app_context():
        user_a_id = seed_users_and_song["user_a"].id
        user_b_id = seed_users_and_song["user_b"].id
        song_id = seed_users_and_song["song"].id

        rate_song(user_b_id, song_id, 5)

        notifications = get_notifications(user_a_id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"


def test_adding_a_friends_song_to_playlist_still_notifies(app, seed_users_and_song):
    """
    Sanity check that the existing 'added to playlist' notification path
    (the one that already works per the bug report) still works, for
    comparison against the missing rating-notification path.

    Note: the song is pre-inserted into playlist_entries directly (with the
    required position/added_by columns) so this test isolates the
    notification behavior from the separate, already-known bug where
    Playlist.songs.append() doesn't populate those NOT NULL columns.
    """
    with app.app_context():
        user_a_id = seed_users_and_song["user_a"].id
        user_b_id = seed_users_and_song["user_b"].id
        song_id = seed_users_and_song["song"].id

        playlist = Playlist(name="Test Playlist", created_by=user_b_id)
        db.session.add(playlist)
        db.session.flush()

        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id,
                song_id=song_id,
                position=1,
                added_by=user_b_id,
            )
        )
        db.session.commit()

        add_to_playlist(playlist.id, song_id, user_b_id)

        notifications = get_notifications(user_a_id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_added_to_playlist"
