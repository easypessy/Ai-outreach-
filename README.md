# 🎯 AI Outreach Finder

A 100% free web app that finds businesses which actually need a specific AI
automation, identifies who the decision-maker is, and writes a personalised
pitch for every lead. Built around the "10 AI Automations You Can Sell" list.

## Why it's completely free (no API keys, no card, no credits)

| Job | How | Cost |
|---|---|---|
| Finding businesses | OpenStreetMap via the public **Overpass API** (3 mirrors) | Free, keyless |
| Finding cities | OpenStreetMap **Nominatim** geocoder (cached) | Free, keyless |
| **Verifying they need it** | The app **live-fetches each lead's website** and checks for existing chat widgets (Tidio, Intercom, Drift…), booking systems (Calendly, Booksy…) and help/support pages. Real evidence, marked ✅ | Free (just visiting their public site) |
| Finding the decision-maker | Role heuristics per business type + a real **name/title pulled from their Team/About page** when present + one-click **LinkedIn / Google / Facebook / website** searches (pre-filled, you open them in your own free browser) | Free |
| Writing pitches | Built-in template engine personalised with each lead's real name, city, phone, website & socials | Free (no LLM) |

## "Does it guess, or verify?"

Both — and every reason on a card is labelled so you know which:

- **✅ verified** — the app actually checked something (e.g. "No live chat widget found on their website — the gap is real", "Already runs Intercom", "Has Calendly — the AI can book straight into it").
- **⚡ signal** — a strong inference from free map data (has a phone line, active socials, business type is a known buyer).
- **🔎 10-sec check** — a manual proof that turns "probably" into "yes": e.g. open their Google reviews and confirm many reviews + zero owner responses (then fill `[REVIEW COUNT]` in the pitch).

The **fit score** blends ✅ + ⚡. It does **not** pretend to be certain — it ranks leads by how much evidence points to a real need, and hands you the two or three things that confirm it.

## Run it

```bash
python3 app.py        # no dependencies — pure Python stdlib
# then open http://localhost:8321
```

## Use it

1. Enter a **city** (type 3+ letters for suggestions).
2. Pick the **business type** (dentists, law firms, restaurants, HVAC, realty,
   salons/spas, gyms, auto shops, hotels, clinics, physio, accounting, or
   **Mixed** as a fallback for sparsely-mapped cities).
3. Pick the **AI service you're selling** (the 5 easy + 5 hard).
4. Set a **radius** and hit **Find leads & generate pitches**.

Each lead card shows:
- **Fit score** (0–100) with "why them" reasons, ranked best-fit first
- Real contact details pulled from the map: address, phone, email, website, Facebook, Instagram
- **Who to pitch**: most likely decision-maker role + ready-to-click searches
- **Your pitch**: personalised email + DM, one click to copy
- ★ **Shortlist** → then **Export CSV** or **Copy all pitches**

## Honest limitations (so you're not surprised)

- **Data density varies.** US/UK/EU cities are rich; some African/Asian cities
  have sparse mapping. The app tells you when data is thin and offers a
  "widen search" button or the Mixed category.
- **[REVIEW COUNT]** in the Review Bot pitch must be filled by you from their
  Google Business profile (a free 10-second check) — that specific number is
  what makes the pitch hit.
- **Decision-maker names** can't be pulled for free at scale (LinkedIn blocks
  it). That's why the app gives you the *role* + pre-filled searches instead —
  one click, and you usually have a name in 30 seconds.
- B2B services (#7 Clay outbound, #8 RAG support, #10 Knowledge bot) target
  bigger companies than maps show — each card includes an extra LinkedIn
  company search for that.

## Files

- `app.py` — backend (HTTP server + Overpass/Nominatim + fit scoring + pitches)
- `index.html` — frontend (single file, no CDNs, works offline once served)
- `test_api.py` — API smoke test (`python3 test_api.py` while the server runs)
