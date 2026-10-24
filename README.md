# MatchPoint Omega: World Tennis (Track 04)

**AI Omega Lisbon Developer Buildathon, 23–24 October 2026**

This is an Omega agent that finds a tennis player the right opponent, court and time. It explains why it chose them, re-plans when something clashes, and asks **both** players before it makes a **simulated** booking.

> Sample players and courts only. No real player data. All bookings and payments are **simulated** and labelled as such.

## What's inside

| Piece | What it does |
|---|---|
| `omega-plugin/tennis/tennis.metta` | An **Omega plugin**. It holds the MeTTa rules for **level fit**, **travel distance** and **availability overlap**, plus 5 skills the agent calls. The sample data is stored as MeTTa facts. |
| `omega-plugin/tennis/tennis.py` | A thin bridge that reports proposals and bookings to the web app. |
| `server/app.py` + `server/static/index.html` | The web app. It **is** Omega's chat channel: Omega's built-in `websocket` channel connects to it. It shows the proposal with its reasons, the clash buttons, both players' confirm buttons, and the bookings. |
| `data/sample.json` | The one source of truth for the sample data. `scripts/gen_facts.py` turns it into MeTTa facts. |

### How Omega is used (checklist mapping)

- **Agent loop:** Omega's native loop reads the player's message, calls `tennis-propose`, explains the result with `send`, records clashes, and re-plans.
- **Memory and reasoning:** clashes are asserted as atoms in the plugin's MeTTa space (`court-taken`, `unavailable`), so every later plan respects them. Omega's own `remember` / long-term memory keeps player preferences and past matches.
- **MeTTa rules:**
  - `level-fit` gives 3 for the same level, 1 for half a level apart, and rejects anything further apart.
  - `within-travel` checks each player against their *own* max km, and `travel-score` rewards a shorter combined trip.
  - `slot-free` requires both players to be available, the court to be open, and the slot not to be blocked in memory.
  - Preferences (surface) and history (a recent rematch gets a small penalty) adjust the score.
- **Confirmation before booking:** this is enforced **in code**. `/api/book` refuses unless that exact match was sent for confirmation and both players pressed Confirm. The LLM cannot skip it.

### Skills the agent gets

```
tennis-propose ana
tennis-court-taken alvalade sat 18
tennis-player-unavailable joao sat all
tennis-request-confirmation ana joao alvalade sat 19
tennis-book ana joao alvalade sat 19        -> SIMULATED, refused until both confirm
```

## API keys

Keys go in a `.env` file in the project folder. Never put them in code. `.env` is git-ignored.

```bash
cp .env.example .env
code .env        # or open it from the file list
```

Set `PROVIDER` and that provider's key:

| PROVIDER | Key variable |
|---|---|
| `OpenAIAPI` | `OPENAIAPI_API_KEY`, plus `OPENAIAPI_URL` and `MODEL` (hackathon SingularityNET endpoint) |
| `ASIOne` | `ASIONE_API_KEY` |
| `Anthropic` | `ANTHROPIC_API_KEY` (model: `ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) |
| `OpenAI` | `OPENAI_API_KEY` |

To change a key, edit `.env` and run `bash run-omega.sh` again.

## Run it (GitHub Codespaces, 4-core)

```bash
pip install -r requirements.txt
python server/app.py              # terminal 1, then open port 8787 in the browser
bash run-omega.sh                 # terminal 2, reads .env
docker logs -f omega-tennis       # watch Omega start
```

When the header shows **Omega connected**, you're live. Run `docker stop omega-tennis` when you're not testing, to stop API usage.

## 3-minute demo script

1. **Ask:** as **Ana**, type *"Find me a match this weekend"*. Omega calls `tennis-propose`, and the card shows **Joao · CT Alvalade · sat 18:00** with the reasons for each rule (same level 3.5, travel 0.5 km / 3.5 km within both limits, both free, clay court Ana likes).
2. **Why:** ask *"Why Joao and not Sara?"* Sara would gain a point because both prefer clay, but she loses one because she and Ana played recently. That leaves her tied at 6, behind Joao in the ranking. Both reasons are visible in the alternatives.
3. **Clash:** click **Mark court as taken**. Omega records it in memory (`tennis-court-taken`), re-plans, and explains what changed (moves to 19:00).
4. **Confirm:** ask Omega to book it. It calls `tennis-request-confirmation`, and the confirmation panel appears. Show that a booking **before** both confirm is refused. Press Confirm for both players.
5. **Book:** Omega makes the booking, stamped **SIMULATED**, ref `SIM-0001`. No court is reserved and no payment is taken.


## Play the booked match

After Omega books a match, press **Play it** (or **Play this match** in the Omega panel's Match tab). The match is played on the booked stadium against the booked opponent.

- **Controls:** arrows or WASD to move, Space to serve, hold a direction as you hit to aim, P to pause.
- **Rules:** serve into the diagonal box with one second serve; faults, double faults, net and out calls; 15/30/40, deuce and advantage. Quick format is first to 3 games with a deciding point at deuce. Full set is first to 6 games by two, with a tiebreak at 6-6.
- **Opponent AI** plays to the opponent's level from the sample data.
- **Stadium surface** changes the bounce: clay is slow and high, grass is fast and low.
- **Atmosphere:** the crowd follows the ball and applauds. The chair umpire calls the score out loud (browser speech).
- **Watch mode** plays AI against AI.
- **Omega panel:** drag it by its header, resize it from the corner, or hide it.

## Settings, customisation and online play

- **Settings** (⚙ in the top bar):
  - **Game:** game speed, opponent difficulty, changeover break length, automatic or manual (Space) swing, and the prediction card.
  - **Player and racket:** four rackets with different power, control and spin; shirt, shorts, skin tone, headwear, and left or right hand.
  - **Sound and view:** commentary on or off, volumes, camera (TV, behind player, overhead), and graphics quality.
- **Ball kids** fetch the ball after each point while play continues.
- **Point predictions** use play coins only. They have no cash value and nothing can be bought or withdrawn.
- **Online:** press **Online → Create a room** and share the 4-letter code or invite link. The other player opens the same page, picks a player, and joins with the code. The host's browser runs the match; the server only relays moves. In GitHub Codespaces, set port 8787 to **Public** (Ports tab → right-click → Port Visibility) so someone outside can open it.
- **Phones and tablets:** a joystick moves your player and a Hit button serves and swings. Landscape gives the best view.
- **Help:** press **? Help** for the full guide to controls, rules, Omega and online play.
- **Offline:** matches against the AI need no internet once the page has loaded (Three.js is served from `server/static/vendor/`). Omega's chat needs its model connection.

## Tests

```bash
# MeTTa rules, outside Omega (needs PeTTa + SWI-Prolog 10)
PETTA=~/PeTTa sh scripts/test_rules.sh
```

## Boundaries

Only sample data is used, with no real player data. Bookings and payments are simulated and labelled. The agent can't book without both confirmations.

## Stretch ideas

Doubles matching for four players; translating between rating systems (NTRP ↔ UTR ↔ ITN); filling a club's empty court hours.