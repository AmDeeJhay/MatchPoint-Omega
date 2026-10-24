"""Python side of the World Tennis Omega plugin.

The MeTTa rules decide the match. This module only reports to the demo web
app (proposals, clashes, confirmation requests, simulated bookings) over HTTP.
The safety rule "no booking before both players confirm" is enforced by the
web app, so the agent cannot skip it even if the LLM tries.
"""
import json
import os
import re
import urllib.error
import urllib.request

SERVER = os.environ.get("TENNIS_SERVER_URL", "http://host.docker.internal:8787").rstrip("/")
TIMEOUT = 8


def _post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(SERVER + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
            return str(body.get("message", "ok"))
    except urllib.error.HTTPError as e:
        try:
            return str(json.loads(e.read().decode("utf-8")).get("message", f"HTTP {e.code}"))
        except Exception:
            return f"ERROR: tennis server returned HTTP {e.code}"
    except Exception as e:  # server down: tell the agent, don't crash the loop
        return f"ERROR: tennis server unreachable at {SERVER} ({e})"


def _s(x):
    return str(x).strip().strip('"')


PLAYER_IDS = {"ana", "joao", "sara", "kofi", "mei", "lucas"}
COURT_IDS = {"alvalade", "estrela", "monsanto", "oriente"}
ALIASES = {"joão": "joao", "saturday": "sat", "sunday": "sun", "sábado": "sat", "domingo": "sun"}


def tokens(args):
    """'Alvalade, Saturday 18:00' -> ['alvalade', 'sat', '18']"""
    raw = re.split(r"[\s,;]+", _s(args).lower())
    out = []
    for t in raw:
        t = t.strip("()[]'\".")
        if not t:
            continue
        t = ALIASES.get(t, t)
        if re.fullmatch(r"\d{1,2}(:\d{2})?(h|am|pm)?", t):
            t = t.split(":")[0].rstrip("hampm")
        out.append(t)
    return out


def arg(args, i):
    t = tokens(args)
    i = int(i)
    return t[i] if i < len(t) else ""


def hour_arg(args, i):
    """Hour as int; -1 means the whole day ('all' or missing)."""
    v = arg(args, i)
    return int(v) if v.isdigit() else -1


def to_int(value):
    """'18', '18:00', 18 -> 18"""
    return int(_s(value).split(":")[0])


def publish_plan(player, plan):
    _post("/api/plan", {"player": _s(player), "plan": _s(plan)})
    return "published"


def publish_event(kind, args):
    _post("/api/event", {"kind": _s(kind), "args": tokens(args)})
    return "published"


def _match_args(args):
    t = tokens(args)
    if len(t) < 5:
        return None, ("ERROR: expected 5 values: player_a player_b court_id day hour "
                      f"(got: {' '.join(t) or 'nothing'})")
    a, b, court, day, hour = t[:5]
    if not hour.isdigit():
        return None, f"ERROR: hour must be a number like 18 (got {hour})"
    return {"a": a, "b": b, "court": court, "day": day, "hour": int(hour)}, None


def request_confirmation(args):
    payload, err = _match_args(args)
    return err or _post("/api/request_confirmation", payload)


def is_booked(result):
    return "yes" if _s(result).startswith("BOOKED") else "no"


def book(args):
    payload, err = _match_args(args)
    return err or _post("/api/book", payload)
