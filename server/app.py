"""World Tennis demo app - the web UI and Omega's chat channel in one process.

* /agent  WebSocket that Omega connects to (Omega's built-in `websocket`
          channel, frames: user_message / agent_message / resume / ack).
* /ui     WebSocket for the browser.
* /api/*  HTTP endpoints called by the Omega tennis plugin (plan, events,
          confirmation request, SIMULATED booking) and by the browser.

The rule "no booking until both players confirm" is enforced HERE, in code.

Run:  python server/app.py      (then open http://localhost:8787)
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "data" / "sample.json").read_text())
PLAYERS = {p["id"]: p for p in SAMPLE["players"]}
COURTS = {c["id"]: c for c in SAMPLE["courts"]}
NAME_TO_PLAYER = {p["name"].lower(): pid for pid, p in PLAYERS.items()}
NAME_TO_COURT = {c["name"].lower(): cid for cid, c in COURTS.items()}
PORT = int(os.environ.get("PORT", "8787"))


def fresh_state():
    return {
        "seq": 0,
        "inbound": [],        # (seq, text) frames sent to Omega, kept for resume replay
        "chat": [],           # what the UI shows
        "plan": None,
        "pending": None,
        "bookings": [],
        "taken": [],          # [court, day, hour] slots no longer free
        "unavailable": [],    # [player, day, hour|"all"]
        "agent_connected": False,
        "ratings": {},        # levels after matches played in the game (set by Omega's MeTTa rules)
    }


S = fresh_state()
AGENTS: set = set()
UIS: set = set()
ROOMS: dict = {}          # online matches: code -> {"host": ws, "guest": ws, "info": {...}}


def now():
    return time.strftime("%H:%M:%S")


DAY_NAMES = {"sat": "Saturday", "sun": "Sunday"}


def slot_label(day, hour):
    return f"{DAY_NAMES.get(day, day)} {int(hour)}:00"


def public_state():
    return {k: v for k, v in S.items() if k not in ("inbound",)}


async def broadcast(kind, payload=None):
    msg = json.dumps({"type": kind, "data": payload, "state": public_state()})
    for ws in list(UIS):
        try:
            await ws.send_str(msg)
        except Exception:
            UIS.discard(ws)


async def chat(role, who, text):
    entry = {"role": role, "who": who, "text": text, "ts": now()}
    S["chat"].append(entry)
    await broadcast("chat", entry)


async def to_agent(who, text, show=True, display=None):
    """Deliver a user message to Omega (queued if Omega is not connected yet)."""
    S["seq"] += 1
    framed = f"[{who}]: {text}"
    S["inbound"].append((S["seq"], framed))
    frame = json.dumps({"type": "user_message", "seq": S["seq"], "text": framed})
    for ws in list(AGENTS):
        try:
            await ws.send_str(frame)
        except Exception:
            AGENTS.discard(ws)
    if show:
        await chat("user", who, display or text)


# ---------------------------------------------------------------- plan parsing
OPTION_RE = re.compile(
    r"^(?P<opp>.+?) at (?P<court>.+?), (?P<day>\w+) (?P<hour>\d+):00 \[score (?P<score>-?[\d.]+)\]\. Why: (?P<why>.*)$")


def parse_plan(player, raw):
    raw = raw.strip()
    if raw.startswith("NO_MATCH"):
        return {"player": player, "best": None, "options": [], "raw": raw}
    body = raw[len("BEST "):] if raw.startswith("BEST ") else raw
    parts = re.split(r" \| Option \d+: ", body)
    options = []
    for part in parts:
        m = OPTION_RE.match(part.strip())
        if not m:
            continue
        d = m.groupdict()
        options.append({
            "opponent": NAME_TO_PLAYER.get(d["opp"].lower(), d["opp"]),
            "opponent_name": d["opp"],
            "court": NAME_TO_COURT.get(d["court"].lower(), d["court"]),
            "court_name": d["court"],
            "day": d["day"], "hour": int(d["hour"]), "score": float(d["score"]),
            "reasons": [r.strip() for r in d["why"].split(";") if r.strip()],
        })
    return {"player": player, "best": options[0] if options else None,
            "options": options[1:], "raw": raw}


# ---------------------------------------------------------------- agent socket
async def agent_ws(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    AGENTS.add(ws)
    S["agent_connected"] = True
    await broadcast("status")
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                frame = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if frame.get("type") == "resume":
                last = frame.get("last_seen_seq")
                for seq, text in S["inbound"]:
                    if last is None or seq > last:
                        await ws.send_str(json.dumps({"type": "user_message", "seq": seq, "text": text}))
            elif frame.get("type") == "agent_message":
                await ws.send_str(json.dumps({"type": "ack", "seq": None, "client_seq": frame.get("client_seq")}))
                await chat("agent", "Omega", str(frame.get("text", "")))
    finally:
        AGENTS.discard(ws)
        S["agent_connected"] = bool(AGENTS)
        await broadcast("status")
    return ws


# ---------------------------------------------------------------- browser socket
async def ui_ws(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    UIS.add(ws)
    await ws.send_str(json.dumps({"type": "hello", "data": SAMPLE, "state": public_state()}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            frame = json.loads(msg.data)
            kind = frame.get("type")
            if kind == "say":
                who = frame.get("who") or "Player"
                text = (frame.get("text") or "").strip()
                if text:
                    await to_agent(who, text)
            elif kind == "court_taken":
                await court_taken(frame)
            elif kind == "player_unavailable":
                await player_unavailable(frame)
            elif kind == "confirm":
                await confirm(frame)
            elif kind == "match_result":
                await match_result(frame)
            elif kind == "coach":
                await coach_request(frame)
            elif kind == "reset":
                keep = S["agent_connected"]
                S.clear()
                S.update(fresh_state())
                S["agent_connected"] = keep
                await broadcast("reset")
    finally:
        UIS.discard(ws)
    return ws


async def court_taken(frame):
    court, day, hour = frame["court"], frame["day"], int(frame["hour"])
    if [court, day, hour] not in S["taken"]:
        S["taken"].append([court, day, hour])
    name = COURTS.get(court, {}).get("name", court)
    await to_agent("Club system",
                   f"{name} (court id {court}) on {slot_label(day, hour)} was just booked by another member. "
                   f"That slot is gone - please re-plan.",
                   display=f"{name}, {slot_label(day, hour)} was just taken by another member.")


async def player_unavailable(frame):
    pid, day = frame["player"], frame["day"]
    if [pid, day, "all"] not in S["unavailable"]:
        S["unavailable"].append([pid, day, "all"])
    name = PLAYERS.get(pid, {}).get("name", pid)
    await to_agent(name, f"Sorry, something came up - I can't play at all on {day} anymore "
                         f"(player id {pid}, day {day}, hour all).")


def stats_line(st):
    if not isinstance(st, dict):
        return ""
    parts = []
    for pid, v in st.items():
        name = PLAYERS.get(pid, {}).get("name", pid)
        parts.append(f"{name}: {v.get('won', 0)} points won, {v.get('aces', 0)} aces, {v.get('df', 0)} double faults, "
                     f"{v.get('net', 0)} into the net, {v.get('out', 0)} out, {v.get('winners', 0)} winners")
    return "; ".join(parts)


async def match_result(frame):
    w, l = frame.get("winner"), frame.get("loser")
    if w not in PLAYERS or l not in PLAYERS:
        return
    gw, gl = int(frame.get("gw", 0)), int(frame.get("gl", 0))
    stadium = str(frame.get("stadium", ""))
    text = (f"MATCH RESULT: {PLAYERS[w]['name']} beat {PLAYERS[l]['name']} {gw}-{gl} at {stadium}. "
            f"Call tennis-record-result {w} {l} {gw} {gl}. Stats: {stats_line(frame.get('stats'))}.")
    await to_agent("Match system", text, display=f"Match finished: {PLAYERS[w]['name']} beat {PLAYERS[l]['name']} {gw}-{gl}. Sent to Omega.")


async def coach_request(frame):
    me, opp = frame.get("player"), frame.get("opponent")
    if me not in PLAYERS or opp not in PLAYERS:
        return
    text = (f"Changeover. {PLAYERS[me]['name']} ({me}) vs {PLAYERS[opp]['name']} ({opp}), games {frame.get('score', '')}. "
            f"Stats: {stats_line(frame.get('stats'))}. Give {PLAYERS[me]['name']} ONE tactical tip, max 20 words.")
    await to_agent("Coach request", text, display=f"{PLAYERS[me]['name']} asked Omega for a tip at the changeover.")


async def api_ratings(request):
    body = await request.json()
    for pid, lvl in (body.get("ratings") or {}).items():
        if pid in PLAYERS:
            S["ratings"][pid] = round(float(lvl), 1)
    await broadcast("ratings", S["ratings"])
    return j("ok")


async def confirm(frame):
    p = S["pending"]
    pid = frame["player"]
    if not p or pid not in (p["a"], p["b"]):
        return
    accept = bool(frame.get("accept", True))
    p["confirmed"][pid] = "yes" if accept else "no"
    other = p["b"] if pid == p["a"] else p["a"]
    court = COURTS[p["court"]]["name"]
    word = "CONFIRMED" if accept else "DECLINED"
    await to_agent(PLAYERS[pid]["name"],
                   f"{word} the match vs {PLAYERS[other]['name']} at {court} on {slot_label(p['day'], p['hour'])} "
                   f"(ids: {p['a']} {p['b']} {p['court']} {p['day']} {p['hour']}).",
                   display=f"{'Confirmed' if accept else 'Declined'}: match vs {PLAYERS[other]['name']}, {slot_label(p['day'], p['hour'])}.")
    await broadcast("pending")


# ---------------------------------------------------------------- plugin API
def j(message, status=200, **extra):
    return web.json_response({"message": message, **extra}, status=status)


async def api_plan(request):
    body = await request.json()
    S["plan"] = parse_plan(body.get("player", ""), body.get("plan", ""))
    await broadcast("plan", S["plan"])
    return j("ok")


async def api_event(request):
    body = await request.json()
    await broadcast("event", body)
    return j("ok")


def same_match(p, a, b, court, day, hour):
    return p and {p["a"], p["b"]} == {a, b} and p["court"] == court and p["day"] == day and p["hour"] == hour


async def api_request_confirmation(request):
    b = await request.json()
    a, bb, court, day, hour = b["a"], b["b"], b["court"], b["day"], int(b["hour"])
    for pid in (a, bb):
        if pid not in PLAYERS:
            return j(f"REFUSED: unknown player id {pid}", 400)
    if court not in COURTS:
        return j(f"REFUSED: unknown court id {court}", 400)
    if [court, day, hour] in S["taken"]:
        return j(f"REFUSED: {COURTS[court]['name']} {slot_label(day, hour)} is already taken. Re-plan.", 409)
    S["pending"] = {"a": a, "b": bb, "court": court, "day": day, "hour": hour,
                    "confirmed": {a: "waiting", bb: "waiting"}}
    await broadcast("pending")
    return j(f"Confirmation requested from {PLAYERS[a]['name']} and {PLAYERS[bb]['name']} for "
             f"{COURTS[court]['name']} {slot_label(day, hour)}. Wait until BOTH reply CONFIRMED, "
             f"then call tennis-book with the same arguments.")


async def api_book(request):
    b = await request.json()
    a, bb, court, day, hour = b["a"], b["b"], b["court"], b["day"], int(b["hour"])
    p = S["pending"]
    if not same_match(p, a, bb, court, day, hour):
        return j("REFUSED: this match was never sent for confirmation. Call tennis-request-confirmation first.", 409)
    waiting = [PLAYERS[x]["name"] for x, v in p["confirmed"].items() if v != "yes"]
    if waiting:
        return j(f"REFUSED: still waiting for confirmation from {', '.join(waiting)}. Do not book yet.", 409)
    if [court, day, hour] in S["taken"]:
        return j("REFUSED: slot was taken in the meantime. Re-plan.", 409)
    ref = f"SIM-{len(S['bookings']) + 1:04d}"
    booking = {"ref": ref, "a": a, "b": bb, "court": court, "court_name": COURTS[court]["name"],
               "day": day, "hour": hour, "simulated": True, "ts": now()}
    S["bookings"].append(booking)
    S["taken"].append([court, day, hour])
    S["pending"] = None
    await broadcast("booking", booking)
    return j(f"BOOKED (SIMULATED - no real court reserved, no payment taken). Ref {ref}: "
             f"{PLAYERS[a]['name']} vs {PLAYERS[bb]['name']}, {COURTS[court]['name']}, {slot_label(day, hour)}.")


async def api_state(_):
    return web.json_response(public_state())


# ---------------------------------------------------------------- online 2-player rooms
# The host's browser runs the match; this server only relays messages between the two players.
def new_code():
    import random
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    while True:
        code = "".join(random.choice(letters) for _ in range(4))
        if code not in ROOMS:
            return code


# ---------------------------------------------------------------- multiplayer lobby
# Players set a profile name in the browser. While the page is open they show as online,
# can invite each other, and an accepted invite opens a room for the two of them.
import re as _re
import uuid as _uuid

USERS: dict = {}      # uid -> {"ws", "name", "level", "kit", "racket", "manual", "status"}
SESS: dict = {}       # ws -> {"uid", "room", "role"}
INVITES: dict = {}    # (from_uid, to_uid) -> time sent
NAME_OK = _re.compile(r"^[A-Za-z0-9_. -]{2,16}$")
INVITE_TTL = 60


def public(uid):
    u = USERS[uid]
    return {"id": uid, "name": u["name"], "level": u["level"], "status": u["status"],
            "color": (u.get("kit") or {}).get("shirt", "#dddddd")}


def match_info(uid):
    u = USERS[uid]
    return {"id": "u_" + uid, "uid": uid, "name": u["name"], "level": u["level"], "kit": u.get("kit") or {},
            "racket": u.get("racket", "allround"), "manual": bool(u.get("manual"))}


async def send(ws, payload):
    if ws is not None and not ws.closed:
        try:
            await ws.send_json(payload)
        except Exception:
            pass


async def broadcast_lobby():
    now = time.time()
    for k in [k for k, t in INVITES.items() if now - t > INVITE_TTL]:
        INVITES.pop(k, None)
    users = [public(uid) for uid in USERS]
    for uid, u in list(USERS.items()):
        await send(u["ws"], {"t": "lobby", "users": users,
                             "sent": [to for (fr, to) in INVITES if fr == uid],
                             "received": [fr for (fr, to) in INVITES if to == uid]})


def drop_invites(uid):
    gone = [k for k in INVITES if uid in k]
    for k in gone:
        INVITES.pop(k, None)
    return gone


async def close_room(ws, notify=True):
    """End the room this socket is in, for both players."""
    sess = SESS.get(ws) or {}
    code, role = sess.get("room"), sess.get("role")
    room = ROOMS.pop(code, None) if code else None
    sess["room"] = sess["role"] = None
    if not room:
        return
    other = room["guest"] if role == "host" else room["host"]
    if other is not None:
        osess = SESS.get(other) or {}
        osess["room"] = osess["role"] = None
        if osess.get("uid") in USERS:
            USERS[osess["uid"]]["status"] = "free"
        if notify:
            await send(other, {"t": "left", "who": role})
    if sess.get("uid") in USERS:
        USERS[sess["uid"]]["status"] = "free"


async def play_ws(request):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=256 * 1024)
    await ws.prepare(request)
    SESS[ws] = {"uid": None, "room": None, "role": None}
    sess = SESS[ws]
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            t = m.get("t")
            me = sess["uid"]

            if t == "hello":                                   # join the lobby with a profile
                prof = m.get("profile") or {}
                name = str(prof.get("name", "")).strip()
                if not NAME_OK.match(name):
                    await send(ws, {"t": "name_bad", "message": "Use 2 to 16 letters, numbers, spaces, dots, dashes or underscores."})
                    continue
                if any(u["name"].lower() == name.lower() and uid != me for uid, u in USERS.items()):
                    await send(ws, {"t": "name_taken", "message": f"Someone online is already called {name}. Pick another name."})
                    continue
                if len(USERS) >= 300 and not me:
                    await send(ws, {"t": "notice", "message": "The lobby is full right now."})
                    continue
                try:
                    level = max(1.0, min(7.0, float(prof.get("level", 3.5))))
                except (TypeError, ValueError):
                    level = 3.5
                uid = me or _uuid.uuid4().hex[:8]
                old = USERS.get(uid, {})
                USERS[uid] = {"ws": ws, "name": name, "level": level, "kit": prof.get("kit") or {},
                              "racket": str(prof.get("racket", "allround")), "manual": bool(prof.get("manual")),
                              "status": old.get("status", "free")}
                sess["uid"] = uid
                await send(ws, {"t": "welcome", "id": uid, "name": name})
                await broadcast_lobby()

            elif t == "invite":
                to = str(m.get("to", ""))
                if not me:
                    await send(ws, {"t": "notice", "message": "Set up your profile first."})
                elif to == me or to not in USERS:
                    await send(ws, {"t": "notice", "message": "That player isn't online any more."})
                elif USERS[to]["status"] != "free":
                    await send(ws, {"t": "notice", "message": f"{USERS[to]['name']} is in a match right now."})
                elif USERS[me]["status"] != "free":
                    await send(ws, {"t": "notice", "message": "Leave your current match first."})
                elif (to, me) in INVITES:
                    await send(ws, {"t": "notice", "message": f"{USERS[to]['name']} already invited you. Accept their invite instead."})
                else:
                    INVITES[(me, to)] = time.time()
                    await send(USERS[to]["ws"], {"t": "invited", "from": public(me)})
                    await send(ws, {"t": "invite_sent", "to": public(to)})
                    await broadcast_lobby()

            elif t == "cancel":
                to = str(m.get("to", ""))
                if INVITES.pop((me, to), None) and to in USERS:
                    await send(USERS[to]["ws"], {"t": "invite_cancelled", "from": public(me)})
                await broadcast_lobby()

            elif t == "answer":
                fr = str(m.get("from", ""))
                sent_at = INVITES.pop((fr, me), None)
                if not me or sent_at is None or fr not in USERS or time.time() - sent_at > INVITE_TTL:
                    await send(ws, {"t": "notice", "message": "That invite has expired."})
                    await broadcast_lobby()
                    continue
                if not m.get("accept"):
                    await send(USERS[fr]["ws"], {"t": "declined", "by": public(me)})
                    await broadcast_lobby()
                    continue
                if USERS[fr]["status"] != "free" or USERS[me]["status"] != "free":
                    await send(ws, {"t": "notice", "message": f"{USERS[fr]['name']} is already in another match."})
                    await broadcast_lobby()
                    continue
                for k in drop_invites(me) + drop_invites(fr):
                    pass
                host_ws = USERS[fr]["ws"]
                code = new_code()
                ROOMS[code] = {"host": host_ws, "guest": ws, "info": match_info(fr)}
                SESS[host_ws].update(room=code, role="host")
                sess.update(room=code, role="guest")
                USERS[fr]["status"] = USERS[me]["status"] = "playing"
                await send(host_ws, {"t": "matched", "code": code, "role": "host", "peer": match_info(me)})
                await send(ws, {"t": "matched", "code": code, "role": "guest", "peer": match_info(fr)})
                await broadcast_lobby()

            elif t == "leave":
                await close_room(ws)
                await broadcast_lobby()

            elif t == "create":                                # room by code (still available)
                await close_room(ws)
                code = new_code()
                ROOMS[code] = {"host": ws, "guest": None, "info": m.get("info", {})}
                sess.update(room=code, role="host")
                if me:
                    USERS[me]["status"] = "playing"
                await send(ws, {"t": "created", "code": code})
                await broadcast_lobby()

            elif t == "join":
                code = str(m.get("code", "")).upper().strip()
                room = ROOMS.get(code)
                if not room:
                    await send(ws, {"t": "error", "message": f"No room with code {code}."})
                elif room["guest"] is not None:
                    await send(ws, {"t": "error", "message": "That room already has two players."})
                elif room["host"] is ws:
                    await send(ws, {"t": "error", "message": "That's your own room."})
                else:
                    await close_room(ws)
                    sess.update(room=code, role="guest")
                    room["guest"] = ws
                    if me:
                        USERS[me]["status"] = "playing"
                    await send(ws, {"t": "joined", "code": code, "info": room["info"]})
                    await send(room["host"], {"t": "guest", "info": m.get("info", {})})
                    await broadcast_lobby()

            elif sess["room"] in ROOMS:                        # in a match: relay as-is
                room = ROOMS[sess["room"]]
                other = room["guest"] if sess["role"] == "host" else room["host"]
                if other is not None and not other.closed:
                    await other.send_str(msg.data)
    finally:
        await close_room(ws)
        uid = sess.get("uid")
        if uid and USERS.get(uid, {}).get("ws") is ws:
            for fr, to in drop_invites(uid):
                other = to if fr == uid else fr
                if other in USERS:
                    await send(USERS[other]["ws"], {"t": "invite_cancelled", "from": {"id": uid, "name": USERS[uid]["name"]}})
            USERS.pop(uid, None)
        SESS.pop(ws, None)
        await broadcast_lobby()
    return ws


async def index(_):
    return web.FileResponse(ROOT / "server" / "static" / "index.html")


def make_app():
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/agent", agent_ws),
        web.get("/ui", ui_ws),
        web.get("/play", play_ws),
        web.get("/api/state", api_state),
        web.post("/api/plan", api_plan),
        web.post("/api/event", api_event),
        web.post("/api/request_confirmation", api_request_confirmation),
        web.post("/api/book", api_book),
        web.post("/api/ratings", api_ratings),
        web.static("/static", ROOT / "server" / "static"),
    ])
    return app


if __name__ == "__main__":
    print(f"World Tennis demo on http://localhost:{PORT}  (Omega connects to ws://<host>:{PORT}/agent)")
    web.run_app(make_app(), host="0.0.0.0", port=PORT, print=None)