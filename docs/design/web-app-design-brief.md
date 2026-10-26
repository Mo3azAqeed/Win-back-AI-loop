# Web app design brief (for Google Stitch or Gemini)

Paste **Prompt 1** into Google Stitch (stitch.withgoogle.com) or Gemini Canvas to design the screens and get the front-end code. Use **Prompt 2** for the illustrations (Gemini image generation). The **data contract** at the end is what the page must call: the backend will serve exactly these shapes, so the design plugs straight in.

---

## Prompt 1: the app (screens, look, motion, code)

```
Design and build a premium, calm web app called "Win-back Lab". It lets a founder test whether an AI email loop wins back stalled merchants better than an email they write themselves. Everything is a simulation: no real email is sent. Audience: a startup founder showing it to their CEO. It must feel like a polished product (think Linear, Stripe, Vercel dashboards), not a developer tool.

WHAT IT DOES
Merchants of a Shopify store-cloning app stall at three stages:
- Idle: signed up, never started a draft. Goal: start a draft.
- Drafter: saved a draft, never published. Goal: publish.
- Trialist: published, so in a 7-day free trial, not paying yet. Goal: pay ($40/month).
The founder writes one email per stage (their "hand-written email"). They press Simulate. The app plays out 13 weeks of merchants, many times over with different luck, and compares three approaches on the same merchants: no email, the founder's email, and the AI loop. The AI loop writes its own email versions each week, tests them, drops the losers and writes new ones. The founder then watches, week by week, what the AI wrote, what was sent, how it did, and how its email changed, side by side with their own.

SCREENS
1. Compose (home)
   - Three cards, one per stage (Idle, Drafter, Trialist), each a realistic email editor: subject line, body, button text, and "send it after" (1 hour / 2 days / 5 days). Pre-filled with the current drafts (from GET /api/drafts). A live preview renders the email as it would look in an inbox, with merchant placeholders like {first_name} shown as soft chips.
   - Run settings: "Quick (20 replays, ~1 min)" or "Full (200 replays, a few minutes)", and an access-code field (password style, remembered locally).
   - One big primary button: "Simulate". It POSTs to /api/runs.
2. Running
   - A calm, beautiful progress state while the run works: an animated loop illustration (emails flowing out, a few coming back), the message "Playing out 13 weeks, 200 times", and the elapsed time. Poll GET /api/runs every 5 seconds; when the run appears in "runs", move to Results with a smooth transition.
3. Results (one run)
   - Hero: a one-line verdict per stage written from the data ("AI loop did better in Idle: +1.9 vs +1.5 points"), with large animated numbers counting up. Green for a win, neutral grey for no gain; never red for the founder's email.
   - Journey funnel: signed up -> started a draft -> published -> paid, three colored bars per step (no email / your email / AI loop), bars growing in on load.
   - THE CENTERPIECE, "Week by week": a horizontal week scrubber (weeks 1 to 15) with a Play button that steps through the weeks like a video (about 1.2 s per week, pausable, draggable). For the selected week and stage it shows two columns:
       Left, "Your email": the founder's email (it never changes), with that week's sends, human clicks and goal actions.
       Right, "AI loop": the email the AI was sending that week (leading subject + body + button), with what changed highlighted (new words fade in, replaced words strike through and fade out), small tags "new this week" / "retired" / "leading", and that week's sends, clicks and goal actions. Below it a short list: "Written this week" (new versions) and "Dropped this week" (with their click rate and sends).
     Above both columns, a line chart of "true lift so far" for the three approaches that draws itself up to the selected week.
   - Per stage tabs or segmented control: Idle / Drafter / Trialist. For Trialists also show the offer the AI chose (none / 7 more trial days / 50% off) and revenue per approach.
   - "How sure are we": the middle-90% range across replays shown as a soft band around the average, and "AI ahead in 186 of 200 replays".
   - A quiet footer note: "Every number is simulated from placeholder assumptions."
4. History
   - A list of past runs (newest first): date, replays, and three small result chips. Clicking opens Results. Include a "Running now" item when a run is in progress.

LOOK AND FEEL
- Premium and calm: generous white space, 8-px spacing grid, large confident typography, soft shadows, 16-px radius cards, subtle glass/blur only on the top bar.
- Fonts: "Inter" for UI and numbers (tabular figures), "Instrument Serif" or "Fraunces" for the few big headline moments.
- Colors (define as CSS variables, with a full dark mode): background #F7F7F5 (dark #0E1116), surface #FFFFFF (dark #161A21), text #14171F (dark #E8EAED), muted #6B7280. Approach colors used everywhere consistently: No email #A1A1AA (grey), Your email #F59E0B (amber), AI loop #4F46E5 (indigo). Success #16A34A.
- Icons: Lucide (outline, 1.5 px stroke).
- Motion: purposeful and smooth, 200-400 ms, ease-out; staggered fade-up of cards on load; number count-ups; chart lines that draw in; funnel bars that grow; the week scrubber animating content changes with crossfades. Respect prefers-reduced-motion (turn animations off).
- Accessible: WCAG AA contrast, keyboard-navigable scrubber (left/right arrows), visible focus rings, charts with text alternatives.
- Responsive: perfect at 390 px phone width (columns stack, scrubber stays usable) and on a 1440 px desktop. No horizontal scrolling.

TECH CONSTRAINTS (important)
- Deliver ONE self-contained index.html: HTML + CSS + vanilla JavaScript, no build step, no framework.
- External scripts only from cdnjs.cloudflare.com with pinned versions (e.g. Chart.js 4.4.1 if you need charts; plain SVG is fine too). Fonts from Google Fonts.
- Talk only to these same-origin endpoints (shapes below): GET /api/drafts, POST /api/runs, GET /api/runs, GET /api/runs/{run}. Handle errors politely (403 wrong access code, 409 a run is already going, 503 runs not switched on).
- Insert all text with textContent (never innerHTML with data), because email text comes from users.
- Ship realistic loading skeletons and empty states.

Use the sample data below to design with real-looking numbers.
```

Then paste the **data contract** section below into the same chat, so the design uses the real field names.

---

## Prompt 2: the illustrations (Gemini image generation)

Generate each at 1600 × 1200, transparent or #F7F7F5 background, same style for all:

```
Style for all images: minimal, premium, soft 3D-flat illustration, rounded shapes, gentle gradients in indigo (#4F46E5), amber (#F59E0B) and warm grey, lots of empty space, no text, no logos, soft shadow, calm and optimistic, consistent lighting from the top left.
```

1. **Hero / running state:** "A loop of envelopes travelling from a small storefront icon around a circular path to three stacked cards and back, a few envelopes glowing as they return."
2. **Empty history:** "A neat empty inbox tray with a single paper plane resting on it."
3. **Week-by-week header:** "Three versions of an email card fanned out, the front one slightly brighter, small sparkles between them suggesting it improved."
4. **Logo mark (square, 512 × 512):** "A simple circular arrow forming a loop around a tiny envelope, single indigo color, geometric, works at 32 px."

Also needed: favicon from the logo mark (32 × 32 and 180 × 180 PNG), and an Open Graph image (1200 × 630) with the logo mark and lots of empty space.

---

## Data contract (what the backend serves)

`GET /api/drafts` → the current hand-written emails (the founder edits these before simulating)

```json
{"emails": [
  {"segment": "idle", "label": "Idle", "goal": "start a draft", "subject": "Your new store is one clone away", "body": "Hi {first_name}, you signed up but haven't started a store yet. ...", "cta": "Start my first draft", "send_after": "2 days"},
  {"segment": "drafter", "label": "Drafter", "goal": "publish", "subject": "{store_name} is ready to go live", "body": "...", "cta": "Publish my store", "send_after": "2 days"},
  {"segment": "trialist", "label": "Trialist", "goal": "pay", "subject": "Keep {store_name} live after your trial", "body": "...", "cta": "Keep my store live", "send_after": "2 days"}
]}
```

`POST /api/runs` body → `{"code": "…", "replays": 20, "emails": [ {segment, subject, body, cta, send_after}, … ]}` → `202 {"run": "2026-10-26-seed4242"}`. Errors: `403` wrong code, `409` a run is going, `503` runs not switched on, `400` bad input (the error text is in `{"error": "…"}`).

`GET /api/runs` → `{"runs": [{"run", "created", "seed", "replays", "headline": [{"merchants", "segments": [{"label", "ai", "hand", "ai_did_better"}]}]}], "running": [{"run", "requested", "replays"}]}`

`GET /api/runs/{run}` → one run (lifts are in percentage points):

```json
{
  "run": "2026-10-26-seed4242", "created": "2026-10-26", "replays": 200, "weeks": 13,
  "summary": ["From 1,000 merchants, the AI loop did better than your email in 2 of 3 stages.", "In Idle the AI loop did better: +1.9 points against +1.5 ..."],
  "your_emails": [{"segment": "idle", "subject": "...", "body": "...", "cta": "...", "send_after": "2 days"}],
  "starts": [{
    "merchants": 1000,
    "journey": {"no_email": [2346, 248, 125, 46], "hand_written": [2346, 288, 143, 51], "ai_loop": [2346, 302, 146, 56]},
    "segments": [{
      "segment": "idle", "label": "Idle", "goal": "start a draft",
      "approaches": [{"approach": "ai_loop", "label": "AI loop", "average": 1.9, "low": 1.4, "high": 2.4}, {"approach": "hand_written", "label": "Your email", "average": 1.5, "low": 1.1, "high": 1.9}, {"approach": "no_email", "label": "No email", "average": 0, "low": 0, "high": 0}],
      "ai_ahead": 186, "ties": 1, "ahead_from_week": 2,
      "weekly_lift": {"no_email": [0, 0, ...], "hand_written": [null, 1.5, ...], "ai_loop": [null, 1.7, ...]},
      "weeks": [{
        "week": 3,
        "hand": {"sent": 140, "clicks": 10, "goal_actions": 8},
        "ai": {
          "sent": 141, "clicks": 14, "goal_actions": 9, "timing": "+1 hour", "offer": null,
          "leading": {"subject": "Clone a store, then make it yours", "body": "Hi {first_name}, pick a store you like ...", "cta": "Clone a store"},
          "written": [{"part": "subject", "text": "Skip the blank page", "by": "stand-in writer"}],
          "dropped": [{"part": "body", "text": "Hi {first_name}, the section builder lets you ...", "sends": 120, "click_rate": 0.075}]
        }
      }]
    }],
    "revenue": {"no_email": 1937, "hand_written": 2133, "ai_loop": 2220}
  }]
}
```

Notes for the designer:
- `weeks` covers weeks 1 to 15 (results keep arriving for two weeks after the last signup). `null` in `weekly_lift` means nothing was known yet that week: draw no point.
- `written[].by` is `"stand-in writer"` until the real AI writer is connected; then it becomes `"AI writer"`. Show it as a small label.
- Only Idle tests new wording; Drafter and Trialist keep their own email, and the AI changes timing (and, for Trialists, the offer). Show that plainly instead of an empty "written" list.
