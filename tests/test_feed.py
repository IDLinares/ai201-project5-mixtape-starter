"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now

# Frozen "current time" used across tests so calendar-day-boundary behavior
# is deterministic instead of depending on the real wall clock.
FROZEN_NOW = datetime(2024, 6, 11, 14, 0, 0, tzinfo=timezone.utc)  # Tuesday, 2:00 PM UTC


def _get_feed(user_id, now=FROZEN_NOW):
    with patch("services.feed_service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        return get_friends_listening_now(user_id)


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_feed(app):
    """
    User A is friends with User B and User C.
    - User B listened to a song earlier today (relative to FROZEN_NOW).
    - User C listened to a song the previous day.
    """
    with app.app_context():
        user_a = User(username="user_a", email="a@example.com")
        user_b = User(username="user_b", email="b@example.com")
        user_c = User(username="user_c", email="c@example.com")
        db.session.add_all([user_a, user_b, user_c])
        db.session.flush()

        def add_friendship(u1, u2):
            db.session.execute(friendships.insert().values(user_id=u1.id, friend_id=u2.id))
            db.session.execute(friendships.insert().values(user_id=u2.id, friend_id=u1.id))

        add_friendship(user_a, user_b)
        add_friendship(user_a, user_c)

        song_b = Song(title="Song B", artist="Artist B", shared_by=user_b.id)
        song_c = Song(title="Song C", artist="Artist C", shared_by=user_c.id)
        db.session.add_all([song_b, song_c])
        db.session.flush()

        event_b = ListeningEvent(
            user_id=user_b.id,
            song_id=song_b.id,
            listened_at=FROZEN_NOW - timedelta(hours=1),  # today, 1:00 PM
        )
        event_c = ListeningEvent(
            user_id=user_c.id,
            song_id=song_c.id,
            listened_at=FROZEN_NOW - timedelta(hours=30),  # previous day
        )
        db.session.add_all([event_b, event_c])
        db.session.commit()

        yield {"user_a": user_a, "user_b": user_b, "user_c": user_c}


def test_friends_listening_now_excludes_previous_day(app, seed_feed):
    """
    Only friends who listened today (calendar day) should appear.
    User B listened earlier today and should be included.
    User C listened the previous day and should NOT be included.
    """
    with app.app_context():
        user_a_id = seed_feed["user_a"].id
        user_b_id = seed_feed["user_b"].id

        results = _get_feed(user_a_id)
        friend_ids = [r["friend"]["id"] for r in results]

        assert friend_ids == [user_b_id]


def test_friends_listening_now_includes_just_after_midnight(app):
    """
    A friend who listened just after midnight today should be included,
    even though many hours have passed since then.
    """
    with app.app_context():
        user_a = User(username="user_a2", email="a2@example.com")
        user_b = User(username="user_b2", email="b2@example.com")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=user_b.id))
        db.session.execute(friendships.insert().values(user_id=user_b.id, friend_id=user_a.id))

        song = Song(title="Song", artist="Artist", shared_by=user_b.id)
        db.session.add(song)
        db.session.flush()

        listened_at = FROZEN_NOW.replace(hour=0, minute=0, second=1)  # 12:00:01 AM today
        event = ListeningEvent(user_id=user_b.id, song_id=song.id, listened_at=listened_at)
        db.session.add(event)
        db.session.commit()

        results = _get_feed(user_a.id)
        friend_ids = [r["friend"]["id"] for r in results]
        assert friend_ids == [user_b.id]


def test_friends_listening_now_excludes_just_before_midnight(app):
    """
    A friend who listened just before midnight yesterday should NOT be
    included, even though it was only a few hours before "now".

    This is the reported bug: someone who listened late last night still
    showed up as "listening now" under the old 24-hour rolling window.
    """
    with app.app_context():
        user_a = User(username="user_a3", email="a3@example.com")
        user_b = User(username="user_b3", email="b3@example.com")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=user_b.id))
        db.session.execute(friendships.insert().values(user_id=user_b.id, friend_id=user_a.id))

        song = Song(title="Late Night Song", artist="Artist", shared_by=user_b.id)
        db.session.add(song)
        db.session.flush()

        listened_at = (FROZEN_NOW - timedelta(days=1)).replace(hour=23, minute=59, second=59)
        event = ListeningEvent(user_id=user_b.id, song_id=song.id, listened_at=listened_at)
        db.session.add(event)
        db.session.commit()

        results = _get_feed(user_a.id)
        friend_ids = [r["friend"]["id"] for r in results]
        assert friend_ids == []


def test_friends_listening_now_with_naive_stored_datetime(app):
    """
    If a listening event is stored with a naive (tz-less) UTC datetime
    instead of an aware one, today's events should still be picked up
    and previous-day ones should still be excluded.
    """
    with app.app_context():
        user_a = User(username="user_a4", email="a4@example.com")
        user_b = User(username="user_b4", email="b4@example.com")
        user_c = User(username="user_c4", email="c4@example.com")
        db.session.add_all([user_a, user_b, user_c])
        db.session.flush()

        for u in (user_b, user_c):
            db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=u.id))
            db.session.execute(friendships.insert().values(user_id=u.id, friend_id=user_a.id))

        song_b = Song(title="Song B", artist="Artist B", shared_by=user_b.id)
        song_c = Song(title="Song C", artist="Artist C", shared_by=user_c.id)
        db.session.add_all([song_b, song_c])
        db.session.flush()

        naive_now = FROZEN_NOW.replace(tzinfo=None)

        event_b = ListeningEvent(
            user_id=user_b.id,
            song_id=song_b.id,
            listened_at=naive_now - timedelta(hours=1),  # today
        )
        event_c = ListeningEvent(
            user_id=user_c.id,
            song_id=song_c.id,
            listened_at=naive_now - timedelta(hours=30),  # previous day
        )
        db.session.add_all([event_b, event_c])
        db.session.commit()

        results = _get_feed(user_a.id)
        friend_ids = [r["friend"]["id"] for r in results]
        assert friend_ids == [user_b.id]


def test_friends_listening_now_dedups_to_most_recent_song(app):
    """
    If a friend has multiple events today, only their most recent
    song should be returned (not an older one).
    """
    with app.app_context():
        user_a = User(username="user_a5", email="a5@example.com")
        user_b = User(username="user_b5", email="b5@example.com")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=user_b.id))
        db.session.execute(friendships.insert().values(user_id=user_b.id, friend_id=user_a.id))

        old_song = Song(title="Old Song", artist="Artist", shared_by=user_b.id)
        new_song = Song(title="New Song", artist="Artist", shared_by=user_b.id)
        db.session.add_all([old_song, new_song])
        db.session.flush()

        older_event = ListeningEvent(
            user_id=user_b.id,
            song_id=old_song.id,
            listened_at=FROZEN_NOW - timedelta(hours=5),
        )
        newer_event = ListeningEvent(
            user_id=user_b.id,
            song_id=new_song.id,
            listened_at=FROZEN_NOW - timedelta(hours=1),
        )
        db.session.add_all([older_event, newer_event])
        db.session.commit()

        results = _get_feed(user_a.id)
        assert len(results) == 1
        assert results[0]["song"]["title"] == "New Song"


def test_friends_listening_now_via_seed_data_pattern(app):
    """
    Mirrors seed_data.py's "older events" loop (hours = 2 + i*8 for
    i in range(8)): only events that fall on today's calendar date
    should surface a friend in the feed.
    """
    with app.app_context():
        user_a = User(username="nova2", email="nova2@example.com")
        friends = [
            User(username=f"friend{i}", email=f"friend{i}@example.com")
            for i in range(4)
        ]
        db.session.add_all([user_a] + friends)
        db.session.flush()

        for f in friends:
            db.session.execute(friendships.insert().values(user_id=user_a.id, friend_id=f.id))
            db.session.execute(friendships.insert().values(user_id=f.id, friend_id=user_a.id))

        songs = [Song(title=f"Track {i}", artist="Various", shared_by=user_a.id) for i in range(4)]
        db.session.add_all(songs)
        db.session.flush()

        today_start = FROZEN_NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        expected_recent_friend_ids = set()
        for i in range(8):
            song = songs[i % len(songs)]
            friend = friends[i % len(friends)]
            listened_at = FROZEN_NOW - timedelta(hours=2 + i * 8)
            if listened_at >= today_start:
                expected_recent_friend_ids.add(friend.id)
            db.session.add(ListeningEvent(
                user_id=friend.id,
                song_id=song.id,
                listened_at=listened_at,
            ))
        db.session.commit()

        results = _get_feed(user_a.id)
        actual_friend_ids = {r["friend"]["id"] for r in results}
        assert actual_friend_ids == expected_recent_friend_ids
