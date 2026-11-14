# F16. Arena phone page and big screen

**Purpose:** make the arena thrilling to use and to watch, at a booth and on a stage.
**Priority:** MUST · **Lane:** Experience · **Checkpoint:** IC3 · **Depends on:** F15 endpoints

## Provides
- `/arena`: the phone page.
- `/arena/screen`: the big screen (projector, booth monitor or laptop).
- The booth "attack station" layout (a tablet or teammate's phone running `/arena` in kiosk-like full screen).

## Behavior

### Phone page (mobile-first, one column, large touch targets, works on iOS Safari and Android Chrome)
1. **Nickname** (remembered).
2. **Mission picker:** cards built from `/v1/arena/goals`. Each card shows the domain icon, the goal title ("Make the agent send money to the attacker", "Plant a phishing link in the team channel", "Leak the deploy key") and the points multiplier.
3. **Payload box** with a live character count (600 max).
4. **"Need an idea?"** chips filled from the domain's hand-tuned attacks. Show only the technique name and a short example, so players adapt rather than copy.
5. A big **"Launch attack"** button.
6. A **status card**: queued (position) → running (three animated lanes) → result.
7. **Result card:** three rows (Naive agent, AgentWall Guard, AgentWall Full). Each shows:
   - an icon: 💥 breached, 🛡 blocked, ⚪ neutralized, ✋ needs approval;
   - a plain one-line reason, e.g. "AgentWall saw the amount came from your ticket, not from the company";
   - points.

   A "shadow" result shows a small "confirming…" tag until the enforced re-run lands.
8. **"Try again"**, the total score and rank.
9. **Breach celebration:** if the player breached Guard or Full, show a full-screen "You found a gap! AgentWall is learning from your attack…". It then follows the Autopilot status live (drafting → proving → patched).

### Big screen (1080p, readable from 10 m, dark theme, high contrast)
- **Left column:**
  - A huge QR code. The URL comes from the API, so the tunnel URL is always current.
  - Counters: "Attacks launched", "Naive agent breaches", "Breaches found", "Breaches patched".
  - "Baseline model: …".
- **Center:** a live ticker of the latest 12 attempts. Each shows nickname, mission, technique tags and three outcome icons. Red Agent attempts carry a robot badge.
- **Right:** the top-10 leaderboard.
- **Breach alarm** (on `arena.breach`):
  - A red flash and "Breach found by <nickname>".
  - A live Autopilot timeline: drafting rule → proving against N attacks and M tasks → ready for review (or auto-enabled in autonomous mode) → "Patched in m:ss".
  - It returns to normal after it's patched or 60 s.
- **Booth mode switch:** a compact layout for a laptop screen, with the reset button visible to the team only (admin cookie).

**Data:** the public arena SSE stream. Counters animate smoothly. The ticker uses a fixed-height list, so there's no layout jump.

## Edge cases
- The tunnel URL changes → the QR code updates from the API.
- The SSE connection drops → it reconnects silently; an amber dot appears in the corner.
- A long nickname → truncated.

## Performance budget
- Lighthouse mobile performance ≥ 90 on `/arena`.
- The screen holds 60 fps animations with 5 events per second.

## Tests and acceptance
- Smoke test: the phone flow end to end against the replay back end.
- **Manual:**
  - An iOS Safari and an Android Chrome phone through the tunnel, by someone who didn't build it.
  - The screen read from the back of the room, on the venue projector if possible.

## Done when
A teammate's phone attack appears on the big screen within 1 s of its result, and the breach alarm plays through to "Patched" with the real Autopilot flow.

## Freedom
Visual design within this spec. Mock it first, with 2 lettered options, and let the team pick before building.
