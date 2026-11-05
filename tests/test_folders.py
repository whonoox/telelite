from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from telethon.tl import functions, types
from telethon.tl.custom import Dialog

from telelite import folders, telegram_client

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def _chat(chat_id, kind="contact", unread=False, muted=False, archived=False, age=0):
    return {
        "chat_id": chat_id,
        "kind": kind,
        "unread": unread,
        "muted": muted,
        "archived": archived,
        "date": NOW - timedelta(minutes=age),
    }


def _folder(**overrides):
    folder = {
        "id": 2,
        "title": "F",
        "pinned": [],
        "include": [],
        "exclude": [],
        "kinds": set(),
        "exclude_muted": False,
        "exclude_read": False,
        "exclude_archived": False,
    }
    folder.update(overrides)
    return folder


# ---- rules ----

def test_category_flags_select_by_kind():
    f = _folder(kinds={"group", "broadcast"})
    assert folders.in_folder(f, _chat(1, kind="group"))
    assert folders.in_folder(f, _chat(2, kind="broadcast"))
    assert not folders.in_folder(f, _chat(3, kind="contact"))


def test_exclude_options_only_apply_to_category_matches():
    f = _folder(
        kinds={"contact"}, include=[9], exclude_muted=True, exclude_read=True, exclude_archived=True
    )
    assert not folders.in_folder(f, _chat(1, muted=True, unread=True))
    assert not folders.in_folder(f, _chat(2, unread=False))
    assert not folders.in_folder(f, _chat(3, unread=True, archived=True))
    assert folders.in_folder(f, _chat(4, unread=True))
    # Hand-picked chats stay even when muted, read and archived.
    assert folders.in_folder(f, _chat(9, muted=True, archived=True))


def test_excluded_chat_is_dropped_from_category():
    f = _folder(kinds={"group"}, exclude=[5])
    assert not folders.in_folder(f, _chat(5, kind="group"))


def test_order_is_folder_pins_then_newest_first():
    f = _folder(kinds={"contact"}, pinned=[3, 1])
    chats = [_chat(1, age=50), _chat(2, age=5), _chat(3, age=99), _chat(4, age=1)]
    assert [c["chat_id"] for c in folders.chats_in_folder(f, chats)] == [3, 1, 4, 2]


# ---- Telegram side, with real Telethon objects ----

def _user(uid, **kw):
    return types.User(id=uid, access_hash=uid, first_name=f"User {uid}", **kw)


def _channel(cid, broadcast):
    return types.Channel(
        id=cid, title=f"Chan {cid}", photo=types.ChatPhotoEmpty(), date=NOW,
        access_hash=cid, broadcast=broadcast, megagroup=not broadcast,
    )


def _raw_dialog(peer, top, unread=0, mute_until=None):
    return types.Dialog(
        peer=peer, top_message=top, read_inbox_max_id=0, read_outbox_max_id=0,
        unread_count=unread, unread_mentions_count=0, unread_reactions_count=0,
        notify_settings=types.PeerNotifySettings(mute_until=mute_until),
    )


def _message(peer, mid, age):
    return types.Message(id=mid, peer_id=peer, date=NOW - timedelta(minutes=age), message="hi")


def test_load_chat_list_fills_folders_and_fetches_old_hand_picked_chats():
    contact = _user(10, contact=True)
    stranger = _user(11)
    news = _channel(20, broadcast=True)
    old_friend = _user(30, contact=True)  # in a folder, but not among the recent chats
    entities = {10: contact, 11: stranger, -1000000000020: news}

    recent = [
        Dialog(None, _raw_dialog(types.PeerUser(10), 1, unread=2), entities,
               _message(types.PeerUser(10), 1, age=1)),
        Dialog(None, _raw_dialog(types.PeerUser(11), 2), entities,
               _message(types.PeerUser(11), 2, age=2)),
        Dialog(None, _raw_dialog(types.PeerChannel(20), 3, unread=5,
                                 mute_until=NOW + timedelta(days=3650)), entities,
               _message(types.PeerChannel(20), 3, age=3)),
    ]
    filters = types.messages.DialogFilters(filters=[
        types.DialogFilterDefault(),
        types.DialogFilter(id=2, title="Channels", pinned_peers=[], include_peers=[],
                           exclude_peers=[], broadcasts=True),
        types.DialogFilter(id=3, title="Friends", contacts=True, exclude_muted=True,
                           pinned_peers=[types.InputPeerUser(30, 30)],
                           include_peers=[types.InputPeerSelf()], exclude_peers=[]),
    ])
    peer_dialogs = types.messages.PeerDialogs(
        dialogs=[_raw_dialog(types.PeerUser(30), 7, unread=1)],
        messages=[_message(types.PeerUser(30), 7, age=600)],
        chats=[], users=[old_friend],
        state=types.updates.State(pts=0, qts=0, date=NOW, seq=0, unread_count=0),
    )
    requested = []

    async def call(request):
        requested.append(type(request).__name__)
        if isinstance(request, functions.messages.GetDialogFiltersRequest):
            return filters
        assert isinstance(request, functions.messages.GetPeerDialogsRequest)
        assert [p.peer for p in request.peers] == [types.InputPeerUser(30, 30), types.InputPeerSelf()]
        return peer_dialogs

    client = AsyncMock(side_effect=call)
    client.get_peer_id.return_value = 99
    client.get_dialogs.return_value = recent

    sections = asyncio_run(telegram_client._load_chat_list(client))
    assert [(s["id"], s["title"]) for s in sections] == [(0, "All chats"), (2, "Channels"), (3, "Friends")]
    all_chats, channels, friends = sections
    assert [c["chat_id"] for c in all_chats["chats"]] == [10, 11, -1000000000020]
    assert [c["chat_id"] for c in channels["chats"]] == [-1000000000020]
    assert [c["chat_id"] for c in friends["chats"]] == [30, 10]  # pinned old friend first
    assert (all_chats["unread"], channels["unread"], friends["unread"]) == (2, 1, 2)
    assert friends["total"] == 2


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_folder_request_failure_degrades_to_plain_list():
    from telethon.errors import RPCError

    async def call(request):
        raise RPCError(request, "FILTERS_UNAVAILABLE", 400)

    client = AsyncMock(side_effect=call)
    client.get_dialogs.return_value = []
    sections = asyncio_run(telegram_client._load_chat_list(client))
    assert [s["title"] for s in sections] == ["All chats"]
