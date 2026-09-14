#!/usr/bin/env python3
"""
AI Outreach Finder
==================
A 100% free lead-finding + pitch-generation tool for selling AI automations.

How it stays free (no API keys, no cards, no credits):
  - Business discovery: OpenStreetMap via the public Overpass API (free, no key)
  - City geocoding: OpenStreetMap Nominatim (free, no key, cached)
  - Decision-maker finding: generates ready-to-click LinkedIn / Google /
    Facebook / website search links (you click them in your own free accounts)
  - Pitches: a built-in template engine personalised with each lead's real
    data (name, city, phone, website, socials). No paid LLM needed.

Stdlib only. Run:  python3 app.py  ->  http://0.0.0.0:8321
"""

import json
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
PORT = 8321
UA = "AIOutreachFinder/1.0 (free lead-finding tool for local sellers)"

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _http_json(url, data=None, timeout=30):
    headers = {"User-Agent": UA}
    body = None
    if data is not None:
        body = data.encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

# ---------------------------------------------------------------------------
# Geocoding (Nominatim) - free, cached in memory
# ---------------------------------------------------------------------------

_geo_cache = {}
_geo_lock = threading.Lock()


def geocode(city: str):
    key = re.sub(r"\s+", " ", city.strip()).lower()
    if not key:
        return None
    with _geo_lock:
        if key in _geo_cache:
            return _geo_cache[key]
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
           + urllib.parse.quote(city.strip()))
    res = _http_json(url, timeout=20)
    if not res:
        with _geo_lock:
            _geo_cache[key] = None
        return None
    it = res[0]
    out = {
        "name": it.get("name") or it.get("display_name", "").split(",")[0],
        "display": it.get("display_name", ""),
        "lat": float(it["lat"]),
        "lon": float(it["lon"]),
    }
    with _geo_lock:
        _geo_cache[key] = out
    return out


def suggest_cities(q: str):
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=6&q="
           + urllib.parse.quote(q))
    res = _http_json(url, timeout=20)
    keep = []
    ql = q.lower()
    for it in res:
        display = it.get("display_name", "")
        name = it.get("name") or display.split(",")[0]
        # only keep results where the query actually appears (drops cross-language fuzz)
        if ql not in display.lower() and ql not in name.lower():
            continue
        keep.append({"label": display, "value": name})
    return keep

# ---------------------------------------------------------------------------
# Overpass (business discovery) - free, mirrors for resilience
# ---------------------------------------------------------------------------

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def overpass(query: str):
    last_err = None
    for url in OVERPASS_MIRRORS:
        try:
            return _http_json(url, data="data=" + urllib.parse.quote(query), timeout=60)
        except Exception as e:  # noqa: BLE001 - try next mirror
            last_err = e
    raise RuntimeError(f"Overpass API unreachable (tried {len(OVERPASS_MIRRORS)} mirrors): {last_err}")


def build_query(lat: float, lon: float, radius_m: int, filters):
    parts = []
    for f in filters:
        parts.append(f'node{f}(around:{radius_m},{lat},{lon});')
        parts.append(f'way{f}(around:{radius_m},{lat},{lon});')
    return ("[out:json][timeout:50];\n(\n" + "\n".join(parts) +
            f"\n);\nout center 80;")

# ---------------------------------------------------------------------------
# Catalog: business categories (OSM tag filters + decision-maker roles)
# ---------------------------------------------------------------------------

CATEGORIES = {
    "dentist": {
        "label": "Dentists",
        "short": "a dental practice",
        "filters": ['["amenity"="dentist"]'],
        "dm_roles": ["Office Manager", "Practice Owner (DMD)"],
        "note": "Great fit: Voice Agent, Chatbot, Review Bot",
    },
    "law": {
        "label": "Law firms",
        "short": "a law firm",
        "filters": ['["office"~"lawyer|law"]'],
        "dm_roles": ["Managing Partner", "Senior Partner"],
        "note": "Great fit: Review Bot, Doc Processing, Chatbot",
    },
    "restaurant": {
        "label": "Restaurants & cafes",
        "short": "a restaurant",
        "filters": ['["amenity"="restaurant"]'],
        "dm_roles": ["Owner", "General Manager"],
        "note": "Great fit: Review Bot, Voice Agent, DM Auto-Responder",
    },
    "hvac": {
        "label": "HVAC / plumbing",
        "short": "an HVAC company",
        "filters": ['["shop"~"hvac"]', '["craft"~"hvac|plumber"]'],
        "dm_roles": ["Owner (usually owner-operated)"],
        "note": "Great fit: Voice Agent, Chatbot — missed calls cost them real money",
    },
    "realty": {
        "label": "Real estate agencies",
        "short": "a real estate agency",
        "filters": ['["office"="estate_agent"]'],
        "dm_roles": ["Managing Broker", "Principal Agent"],
        "note": "Great fit: DM Auto-Responder, Chatbot, Review Bot",
    },
    "beauty": {
        "label": "Salons, spas & med spas",
        "short": "a salon",
        "filters": ['["shop"~"beauty|hairdresser"]', '["amenity"="spa"]'],
        "dm_roles": ["Owner", "Salon Manager"],
        "note": "Great fit: DM Auto-Responder, Review Bot, Voice Agent",
    },
    "gym": {
        "label": "Gyms & fitness studios",
        "short": "a gym",
        "filters": ['["leisure"="fitness_centre"]'],
        "dm_roles": ["Owner", "General Manager"],
        "note": "Great fit: DM Auto-Responder, Voice Agent",
    },
    "auto": {
        "label": "Auto repair shops",
        "short": "an auto shop",
        "filters": ['["shop"="car_repair"]'],
        "dm_roles": ["Shop Owner", "Service Manager"],
        "note": "Great fit: Review Bot, Voice Agent",
    },
    "hotel": {
        "label": "Hotels & B&Bs",
        "short": "a hotel",
        "filters": ['["tourism"="hotel"]'],
        "dm_roles": ["General Manager", "Owner"],
        "note": "Great fit: Voice Agent, Chatbot, Review Bot",
    },
    "clinic": {
        "label": "Clinics & doctors",
        "short": "a medical clinic",
        "filters": ['["amenity"~"clinic|doctors"]'],
        "dm_roles": ["Practice Manager", "Medical Director"],
        "note": "Great fit: Voice Agent, Chatbot",
    },
    "physio": {
        "label": "Physiotherapy & chiropractic",
        "short": "a physiotherapy clinic",
        "filters": ['["office"="physiotherapist"]'],
        "dm_roles": ["Clinic Owner", "Head Physiotherapist"],
        "note": "Great fit: Chatbot, Review Bot, Voice Agent",
    },
    "accounting": {
        "label": "Accounting firms",
        "short": "an accounting firm",
        "filters": ['["office"="accountant"]'],
        "dm_roles": ["Managing Partner", "Controller"],
        "note": "PERFECT fit: AI Document Processing — they live inside this pain",
    },
    "mixed": {
        "label": "Mixed — all local businesses (fallback)",
        "short": "a local business",
        "filters": [
            '["shop"]',
            '["amenity"~"^(restaurant|cafe|bar|clinic|doctors|dentist|bank|pharmacy)$"]',
            '["office"]',
            '["leisure"="fitness_centre"]',
            '["tourism"="hotel"]',
        ],
        "dm_roles": ["Owner", "Manager"],
        "note": "Use this when a specific category has little OpenStreetMap data in your city",
    },
}

# Elements with these tags are public institutions / non-buyers — drop them
EXCLUDE_AMENITY = {
    "police", "court", "prison", "place_of_worship", "community_centre",
    "public_building", "townhall", "post_office", "school", "university",
    "college", "kindergarten", "library", "shelter", "grave_yard", "memorial",
    "monument", "fountain", "toilets", "drinking_water", "recycling",
}
EXCLUDE_OFFICE = {"government", "embassy", "ngo"}
EXCLUDE_SHOP = {"doityourself"}
EXCLUDE_BUILDING = {"cathedral", "church", "temple", "mosque", "synagogue"}

# ---------------------------------------------------------------------------
# Catalog: the 10 AI services (from your article) with pitch templates
# Placeholders: {business} {city} {first} {website} {phone} {category}
#               {role} {review_count} {you}
# ---------------------------------------------------------------------------

SERVICES = {
    "chatbot": {
        "label": "1. AI Website Chatbot",
        "tier": "easy",
        "price": "Setup $997–$2,500  •  $97–$297/mo",
        "learn": "1–2 weeks",
        "buyers": "Dentists, law firms, HVAC, med spas, realtors — any local business with a website that gets after-hours visitors",
        "b2b": False,
        "boost_cats": ["dentist", "law", "clinic", "physio", "realty", "hotel"],
        "dm_extra_roles": ["Owner"],
        "email_subject": "Quick question about {business}'s website",
        "email_body": (
            "Hi {first},\n\n"
            "I was on {business}'s website and noticed something that's probably costing you a few leads a week: "
            "after hours, there's nobody to answer visitor questions.\n\n"
            "When someone lands at 9pm and asks \"do you take walk-ins?\" or \"how much does a cleaning cost?\" — "
            "they leave, and usually go to whoever answers first.\n\n"
            "I build smart website assistants for {category} that:\n"
            "1. Answer every question instantly, using your own website + FAQ (no wrong answers)\n"
            "2. Qualify the visitor (name, number, what they need)\n"
            "3. Book them straight into your calendar\n\n"
            "Setup is $997–$2,500, then about $97–$297/mo. I can have it live on your site within a week.\n\n"
            "Want me to build one on your actual website and send you a 2-minute recording of it in action?\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build smart website assistants for {category} that answer visitor questions 24/7 and book them "
            "straight into your calendar (no wrong answers — it only uses your own site + FAQ). "
            "Want me to set one up on {business}'s website and send you a 2-min demo?"
        ),
    },
    "dm": {
        "label": "2. Instagram/FB DM Auto-Responder",
        "tier": "easy",
        "price": "Setup $500–$1,500  •  $97–$197/mo",
        "learn": "1–2 weeks",
        "buyers": "Coaches, course creators, e-commerce, realtors, fitness trainers, beauty brands",
        "b2b": False,
        "boost_cats": ["beauty", "gym", "realty", "dentist", "restaurant"],
        "dm_extra_roles": ["Social Media Manager"],
        "email_subject": "Your DMs are quietly costing you leads",
        "email_body": (
            "Hi {first},\n\n"
            "I noticed {business} runs an active social presence — and I'll guess the pattern: someone DMs "
            "\"how much?\" or \"info please\", it sits for 8 hours, and by the time it's answered the lead has "
            "moved on.\n\n"
            "I build automated DM responders (ManyChat-powered) that reply in 3 seconds, answer the question, ask "
            "qualifying questions, and either book the call or send the checkout link — 24/7.\n\n"
            "The most popular format is the \"DM us the word BOOK\" funnel — it books 5–15 calls/week on autopilot.\n\n"
            "Setup $500–$1,500, then $97–$197/mo.\n\n"
            "Want to see it running on your actual page? Send me your handle and I'll mock it up in a day.\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! Quick one — when a lead DMs \"how much?\" on {business}'s page, how fast does it get "
            "answered? I build automated DM responders that reply in 3 seconds, qualify them and book the call, 24/7. "
            "Want me to mock one up on your page?"
        ),
    },
    "email_support": {
        "label": "3. AI Email Support Auto-Responder",
        "tier": "easy",
        "price": "Setup $1,500–$3,000  •  $200–$500/mo",
        "learn": "2–3 weeks",
        "buyers": "E-commerce stores (Shopify/WooCommerce), SaaS, subscription boxes — any drowning support@ inbox",
        "b2b": False,
        "boost_cats": [],
        "dm_extra_roles": ["Head of Support", "Ops Manager"],
        "email_subject": "How many hours a week go to \"where's my order?\"",
        "email_body": (
            "Hi {first},\n\n"
            "Straight question: how many hours a week does {business}'s team spend answering the same 10 emails — "
            "\"where's my order?\", \"how do I reset my password?\", \"what's your return policy?\"\n\n"
            "I build a system that reads each support email, drafts the correct reply from your help docs + policies, "
            "and auto-sends the simple ones. Complex ones go to a human as an approved draft with full context.\n\n"
            "Teams usually cut 50–70% of routine support time.\n\n"
            "Setup $1,500–$3,000, then $200–$500/mo.\n\n"
            "Send me your 5 most-asked questions and I'll show you exactly how it would answer each one.\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build a system that auto-answers the repetitive support emails (\"where's my order?\", "
            "returns, passwords) using your own help docs — humans only approve the tricky ones. "
            "Worth a 10-min look at how it would handle {business}'s top 5 questions?"
        ),
    },
    "content": {
        "label": "4. AI Content Repurposing Pipeline",
        "tier": "easy",
        "price": "Setup $1,500–$3,000  •  $297–$797/mo",
        "learn": "2–4 weeks",
        "buyers": "Podcasters, YouTubers, coaches, agency owners, B2B founders",
        "b2b": False,
        "boost_cats": [],
        "dm_extra_roles": ["Content Manager", "Creator (owner)"],
        "linkedin_search": "podcast {city} OR \"youtube channel\" {city}",
        "email_subject": "Your best content is sitting in one video",
        "email_body": (
            "Hi {first},\n\n"
            "Most creators make one long-form piece a week and let it die there. I build a repurposing pipeline that takes "
            "one podcast episode or YouTube video and automatically turns it into:\n\n"
            "• 5 short-form clips (captioned)\n"
            "• 1 blog post\n"
            "• 7 LinkedIn/Twitter posts\n"
            "• 1 newsletter issue\n"
            "• Image captions — all scheduled to publish automatically\n\n"
            "One hour of recording becomes a full week of content.\n\n"
            "Setup $1,500–$3,000, then $297–$797/mo to run it for you.\n\n"
            "Send me a link to one episode/video and I'll show you exactly what the pipeline would produce from it.\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build a pipeline that turns one podcast episode or video into 5 clips, a blog post, "
            "7 social posts and a newsletter — all scheduled automatically. "
            "Send me one of your episodes and I'll show you what it would turn into."
        ),
    },
    "reviews": {
        "label": "5. AI Review Response Bot (Google/Yelp)",
        "tier": "easy",
        "price": "Setup $500–$1,500  •  $97–$297/mo",
        "learn": "1–2 weeks",
        "buyers": "Restaurants, hotels, dental, auto shops, salons — businesses that know reviews matter but never respond",
        "b2b": False,
        "boost_cats": ["restaurant", "hotel", "auto", "beauty", "dentist", "gym"],
        "dm_extra_roles": ["Owner"],
        "email_subject": "{business} has [REVIEW COUNT] Google reviews — and zero replies",
        "email_body": (
            "Hi {first},\n\n"
            "I checked your Google Business profile — [REVIEW COUNT] reviews, and the business hasn't responded "
            "to a single one.\n\n"
            "This matters twice over: Google rewards businesses that respond (better local rankings, higher "
            "click-through), and potential customers read your responses as carefully as the reviews themselves.\n\n"
            "I can set up a system that drafts a personalised, on-brand reply for every new review within the hour — "
            "positive ones thanked warmly, negative ones handled professionally. You approve with one click "
            "(or it auto-posts, your choice).\n\n"
            "Setup $500–$1,500, then $97–$297/mo.\n\n"
            "Shall I draft 3 sample replies to your oldest unanswered reviews so you can see the quality?\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! Checked {business}'s Google reviews — you've got [REVIEW COUNT] and zero responses. "
            "Google quietly penalises that in local rankings. I can auto-draft a personalised reply to every "
            "new review within the hour ($97–$297/mo). Want 3 free samples?"
        ),
    },
    "voice": {
        "label": "6. AI Voice Agent for Phone Calls",
        "tier": "hard",
        "price": "Setup $2,500–$7,500  •  $497–$1,997/mo",
        "learn": "4–8 weeks",
        "buyers": "Dental, med spas, HVAC, law firms, dealerships, property management — businesses that miss calls",
        "b2b": False,
        "boost_cats": ["dentist", "clinic", "hvac", "hotel", "auto", "realty"],
        "dm_extra_roles": ["Owner", "Office Manager"],
        "email_subject": "You're missing calls right now",
        "email_body": (
            "Hi {first},\n\n"
            "Every call {business} misses is usually a $500–$5,000 customer — and for {category}, the phones "
            "are almost always busy exactly when the callers are.\n\n"
            "I build voice agents that answer your front desk 24/7. Real voice, real conversation: they answer "
            "questions about services and hours, book appointments straight into your calendar, handle "
            "cancellations, and transfer to a human when something's too complex. Callers rarely realise they're "
            "talking to a machine.\n\n"
            "Dental, med spa and HVAC offices typically take missed calls down to near zero.\n\n"
            "Setup $2,500–$7,500, then $497–$1,997/mo (includes call minutes).\n\n"
            "I can send you a 30-second recording of one answering a live caller — want me to?\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build phone agents that answer the front desk 24/7 — real voice, answers questions, "
            "books appointments into your calendar, transfers to a human when needed. "
            "Want a 30-sec recording of one handling a caller for {business}?"
        ),
    },
    "clay_outbound": {
        "label": "7. AI Lead Enrichment & Outbound System",
        "tier": "hard",
        "price": "Setup $3,000–$8,000  •  $1,000–$4,000/mo",
        "learn": "4–8 weeks",
        "buyers": "B2B SaaS, marketing agencies, IT services, consulting, recruiting firms",
        "b2b": True,
        "boost_cats": ["law", "accounting"],
        "dm_extra_roles": ["Founder", "VP Sales", "Head of Growth"],
        "linkedin_search": "B2B SaaS {city} (VP Sales OR Founder OR \"Head of Growth\")",
        "email_subject": "Your cold emails still feel cold",
        "email_body": (
            "Hi {first},\n\n"
            "Most outbound reads \"I noticed you're in the [industry] space\" — and gets deleted in one second.\n\n"
            "I build Clay-powered research pipelines that check every prospect before the email goes out: their website, "
            "recent news, the decision-maker's LinkedIn — then write a genuinely specific first line for each of "
            "the 1,000 emails. The result: cold email that feels warm, and reply rates that look like warm leads.\n\n"
            "Setup $3,000–$8,000, then $1,000–$4,000/mo (list building, copy iteration, deliverability).\n\n"
            "I'll audit your current outbound for free — 15 minutes, no pitch. Worth it?\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build Clay-powered outbound pipelines — every prospect researched, every email line "
            "genuinely specific. I do free 15-min outbound audits (no pitch). Want me to look at yours?"
        ),
    },
    "rag_support": {
        "label": "8. Custom AI Support Agent (RAG)",
        "tier": "hard",
        "price": "Setup $5,000–$15,000  •  $1,000–$3,000/mo",
        "learn": "6–12 weeks",
        "buyers": "SaaS (post-Series A), e-commerce doing $2M+/yr, fintech, healthtech — 500+ tickets/mo",
        "b2b": True,
        "boost_cats": [],
        "dm_extra_roles": ["Head of Support", "Head of Customer Success", "CTO"],
        "linkedin_search": "SaaS {city} (\"Head of Support\" OR \"Customer Success\" OR CTO)",
        "email_subject": "Deflect 50–70% of your support tickets",
        "email_body": (
            "Hi {first},\n\n"
            "I build support agents that have read your entire knowledge base — help docs, past tickets, "
            "pricing, policies — and answer complex, specific questions accurately (not just FAQ parrots). "
            "They check order status via your help-desk API and escalate to a human with full context when they "
            "can't help.\n\n"
            "Teams running 500+ tickets/mo typically deflect 50–70% without shrinking the quality bar.\n\n"
            "Setup $5,000–$15,000, then $1,000–$3,000/mo.\n\n"
            "Here's the offer: I'll build a free demo trained on your public help docs. If it's not accurate "
            "enough to be impressed, we part friends.\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build support agents trained on your full help docs + past tickets — they deflect "
            "50–70% of volume and escalate with full context. I'll train one on your public docs for free; "
            "if it's not impressive, no hard feelings. Interested?"
        ),
    },
    "doc_processing": {
        "label": "9. AI Document Processing Pipeline",
        "tier": "hard",
        "price": "Setup $5,000–$20,000  •  $500–$3,000/mo or $0.50–$3/doc",
        "learn": "6–10 weeks",
        "buyers": "Accounting firms, mid-market CFOs, logistics, law firms, real estate, insurance",
        "b2b": False,
        "boost_cats": ["accounting", "law"],
        "dm_extra_roles": ["Controller", "Managing Partner", "CFO"],
        "email_subject": "80 hours of invoice entry a month → 5",
        "email_body": (
            "Hi {first},\n\n"
            "I build automated pipelines that read every invoice, PO or contract — PDFs, scans, emails — extract the "
            "fields (vendor, line items, amounts, due dates, PO numbers), validate them, and push them straight "
            "into QuickBooks/Xero. Humans only review the flagged exceptions.\n\n"
            "Accounting firms and mid-market finance teams typically cut document processing time by ~90% "
            "(e.g. 80 hours/month of manual entry down to about 5).\n\n"
            "Setup $5,000–$20,000 (scales with document types), then $500–$3,000/mo or $0.50–$3 per document.\n\n"
            "The ROI is usually visible within the first month. Can I see a sample of your messiest document "
            "type so I can show you exactly how it would be handled?\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I cut invoice/contract processing time ~90% with an automated extraction pipeline "
            "(PDF/scan/email → validated → straight into your accounting system). "
            "Worth a 15-min look at your messiest document type?"
        ),
    },
    "knowledge_bot": {
        "label": "10. AI Internal Knowledge Bot (Slack/Teams)",
        "tier": "hard",
        "price": "Setup $8,000–$30,000+  •  $1,000–$5,000/mo",
        "learn": "8–16 weeks",
        "buyers": "100–2,000 employee companies: tech, consulting, healthcare, franchise HQs",
        "b2b": True,
        "boost_cats": [],
        "dm_extra_roles": ["VP Operations", "Head of People", "CTO"],
        "linkedin_search": "company {city} (\"VP Operations\" OR \"Head of People\" OR CTO)",
        "email_subject": "New hires take 3 months to find answers",
        "email_body": (
            "Hi {first},\n\n"
            "Every question your employees type into Slack — \"what's the PTO policy for new hires?\", \"how do I "
            "submit an expense report?\", \"what's the rate limit on the v2 endpoint?\" — takes minutes to find, "
            "hours to get answered, and it lives in 15 different tools.\n\n"
            "I build internal knowledge bots that answer instantly, trained on your Notion/Confluence/Drive/SharePoint, "
            "with citations and proper access controls (not everyone sees HR docs).\n\n"
            "Companies with 100–2,000 employees typically cut new-hire ramp from ~3 months to ~3 weeks.\n\n"
            "Setup $8,000–$30,000, then $1,000–$5,000/mo.\n\n"
            "On a 20-min call I can take 3 real questions from your team and show you exactly what the bot "
            "would do with them.\n\n"
            "— {you}"
        ),
        "dm_text": (
            "Hi {first}! I build internal knowledge bots for docs (Slack/Teams) — instant answers with "
            "citations, proper access controls. New-hire ramp: 3 months → 3 weeks. "
            "Worth a 20-min look?"
        ),
    },
}

# ---------------------------------------------------------------------------
# Lead parsing + fit scoring
# ---------------------------------------------------------------------------

def parse_elements(elements):
    seen = set()
    leads = []
    for el in elements:
        tags = el.get("tags") or {}
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None and el.get("center"):
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")
        if lat is None:
            continue
        name = tags.get("name")
        if not name:
            continue
        # drop public institutions / clearly non-business entries
        if (tags.get("amenity") in EXCLUDE_AMENITY
                or tags.get("office") in EXCLUDE_OFFICE
                or tags.get("shop") in EXCLUDE_SHOP
                or tags.get("building") in EXCLUDE_BUILDING
                or tags.get("GNS:dsg_code")):  # auto-imported geographic names, not businesses
            continue
        key = (round(lat, 4), round(lon or 0, 4))
        if key in seen:
            continue
        seen.add(key)

        def t(*keys):
            for k in keys:
                v = tags.get(k)
                if v:
                    return v
            return None

        street = t("addr:street", "address:street")
        house = t("addr:housenumber", "address:housenumber")
        suburb = t("addr:suburb", "address:suburb", "addr:city", "address:city")
        parts_a = []
        if house and street:
            parts_a.append(f"{house} {street}")
        elif street:
            parts_a.append(street)
        if suburb:
            parts_a.append(suburb)
        leads.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "address": ", ".join(parts_a),
            "phone": t("phone", "contact:phone"),
            "email": t("email", "contact:email"),
            "website": t("website", "contact:website", "url"),
            "facebook": t("contact:facebook", "facebook"),
            "instagram": t("contact:instagram", "instagram"),
            "contact_person": t("contact:name"),
        })
    return leads


# ---------------------------------------------------------------------------
# Live website verification (free — just fetching their public homepage)
# ---------------------------------------------------------------------------

CHAT_FINGERPRINTS = [
    ("tidio", "Tidio"), ("intercom", "Intercom"), ("drift.com", "Drift"),
    ("crisp.chat", "Crisp"), ("crisp.website", "Crisp"), ("livechat", "LiveChat"),
    ("tawk.to", "Tawk.to"), ("tawkto", "Tawk.to"), ("zopim", "Zendesk"),
    ("zendesk", "Zendesk"), ("botpress", "Botpress"), ("chatwoot", "Chatwoot"),
    ("typebot", "Typebot"), ("landbot", "Landbot"), ("jivosite", "Jivochat"),
    ("freshchat", "Freshchat"), ("fb-customerchat", "Messenger"),
    ("smartsupp", "Smartsupp"), ("olark", "Olark"), ("purechat", "PureChat"),
    ("chatbase", "Chatbase"), ("reamaze", "Reamaze"), ("hs-collect", "HubSpot"),
]
BOOKING_FINGERPRINTS = [
    ("calendly", "Calendly"), ("acuityscheduling", "Acuity Scheduling"),
    ("booksy", "Booksy"), ("treatwell", "Treatwell"), ("setmore", "SetMore"),
    ("square.appointments", "Square Appointments"), ("book.square", "Square Appointments"),
    ("cal.com", "Cal.com"), ("youcanbookme", "YouCanBookMe"),
    ("zoho.com/bookings", "Zoho Bookings"),
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

TITLE_KEYWORDS = ("owner", "founder", "director", "manager", "principal",
                  "partner", "ceo", "head of", "president", "co-owner",
                  "dentist", "dds", "dmd", "doctor", "physician", "md,")


def fetch_html(url, timeout=12):
    if not url.startswith("http"):
        url = "https://" + url
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(1_500_000)
        return True, raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - site down/blocked -> just report it
        return False, ""


PERSON_STOP = {
    "our team", "the team", "meet the", "our story", "why we", "book now",
    "get in", "call us", "open now", "our mission", "our values", "our approach",
    "our location", "our clinic", "our office", "our practice", "our doctors",
    "our dentists", "our staff", "our clients", "our patients", "terms of",
    "privacy policy", "our services", "our history", "our philosophy",
}


def find_person(html):
    """Heuristic: find 'Name is the owner/founder/...' or a heading name + title line."""
    cands = []
    name_pat = r"(?:Dr\.?\s+)?([A-Z][a-zA-Z''\-]+(?: [A-Z][a-zA-Z''\-]+){1,2})"
    # "Name is the/our owner/founder/doctor/dentist"
    for m in re.finditer(name_pat + r"\s+(?:is|was)\s+(?:our|the|a)\s+"
                         r"([A-Za-z][A-Za-z ,.'\-]{0,28}?)(?=[.,;—–<\n]|$)", html):
        name, title = m.group(1).strip(), m.group(2).strip()
        if any(k in title.lower() for k in TITLE_KEYWORDS) and name.lower() not in PERSON_STOP:
            cands.append({"name": name, "title": title})
    # heading name + a title in the very next element
    for m in re.finditer(
            r"<h[1-4][^>]*>\s*(?:Dr\.?\s+)?([A-Z][a-zA-Z''\-]+(?: [A-Z][a-zA-Z''\-]+)+?)\s*</h[1-4]>"
            r"\s*<[^>]{0,80}>\s*([A-Za-z][A-Za-z ,.'\-]{0,24}?)(?:<|</)", html):
        name, title = m.group(1).strip(), m.group(2).strip()
        if (any(k in title.lower() for k in TITLE_KEYWORDS)
                and name.lower() not in PERSON_STOP and len(name.split()) <= 3):
            cands.append({"name": name, "title": title})
    # "Dr. Name" headings (dental/medical team pages)
    for m in re.finditer(r"<h[1-4][^>]*>\s*(Dr\.[A-Za-z .''\-]{2,30}?)\s*</h[1-4]>", html):
        name = m.group(1).strip().strip(".")
        if name.lower() not in PERSON_STOP and 2 <= len(name.split()) <= 3:
            cands.append({"name": name, "title": "Doctor (listed on team page)"})
    # "Dr. Name, DDS/DMD/MD" anywhere on the page
    for m in re.finditer(r"Dr\.\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,?\s*(DDS|DMD|MD)\b", html):
        name = m.group(1).strip()
        if name.lower() not in PERSON_STOP:
            cands.append({"name": f"Dr. {name}", "title": f"{m.group(2)} (listed on site)"})
    seen, out = set(), []
    for c in cands:
        if c["name"].lower() not in seen:
            seen.add(c["name"].lower())
            out.append(c)
    return out[:3]


def site_check(lead, home_timeout=5, about_timeout=4):
    """Fetch the lead's homepage (and about/team page) for real evidence."""
    url = lead.get("website")
    if not url:
        return None
    ok, html = fetch_html(url, timeout=home_timeout)
    if not ok:
        return {"ok": False, "chat": None, "booking": None, "support_pages": 0, "person": None}
    low = html.lower()
    chat = next((label for pat, label in CHAT_FINGERPRINTS if pat in low), None)
    booking = next((label for pat, label in BOOKING_FINGERPRINTS if pat in low), None)
    support_pages = len(set(re.findall(
        r'href=["\']([^"\']*(?:help|faq|support|shipping|return|polic)[^"\']*)["\']', low)))
    person = None
    hrefs = re.findall(r'href=["\']([^"\']{2,90})["\']', html)
    seen_urls, candidates = set(), []
    for h in hrefs:
        h = h.strip()
        hl = h.lower()
        if hl.startswith(("about:", "javascript:", "mailto:", "tel:", "#")) or not hl:
            continue
        if not re.search(r"about|team|staff|provider|doctor|meet-?us|our-story", hl):
            continue
        full = urllib.parse.urljoin(url, h)
        key = urllib.parse.urldefrag(full)[0].lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        candidates.append(full)
        if len(candidates) >= 3:
            break
    for p in candidates:
        _, phtml = fetch_html(p, timeout=about_timeout)
        if phtml and len(phtml) > 200:
            person = find_person(phtml) or None
            if person:
                break
    return {"ok": True, "chat": chat, "booking": booking,
            "support_pages": support_pages, "person": person}


def fit_score(lead, service_key, cat_key, site=None):
    s = SERVICES[service_key]
    score = 42
    reasons = []  # each: {"t": text, "k": "verified"|"signal"|"check"}

    def add(text, kind="signal", delta=0):
        nonlocal score
        score += delta
        reasons.append({"t": text, "k": kind})

    # ---- capability signals (free, from map data — educated inference) ----
    if lead.get("website"):
        if service_key in ("chatbot", "rag_support"):
            add("Has a live website — the AI connects to it directly", "signal", 12)
        else:
            add("Has a live website (verified online presence)", "signal", 5)
    else:
        if service_key == "chatbot":
            add("No website found — pitch chatbot + basic site as a bundle", "signal", 0)
        if service_key == "voice":
            add("No website — phone is their main channel", "signal", 6)

    if lead.get("phone"):
        if service_key in ("voice", "chatbot"):
            add("Public phone line — the #1 channel to automate", "signal", 14)
        else:
            add("Reachable by phone for first outreach", "signal", 3)

    if lead.get("facebook") or lead.get("instagram"):
        if service_key == "dm":
            add("Active social profile — DM volume is likely high", "signal", 18)
        elif service_key == "reviews":
            add("Marketing-driven business — cares about reputation", "signal", 4)
        else:
            add("Runs social media — extra channel to reach them", "signal", 2)

    if lead.get("email"):
        add("Public email address — fastest path to first touch", "signal", 2)

    if cat_key in s.get("boost_cats", []):
        add("This business type is a known buyer of this service", "signal", 10)

    if service_key == "reviews":
        add("Review responses lift local SEO rankings and conversion", "signal", 4)
        add("10-sec check: open their Google reviews — many reviews + zero owner "
            "responses = send the pitch with the exact count", "check", 0)

    if s.get("b2b"):
        add("B2B service — use the LinkedIn company search below for bigger targets", "signal", 0)

    # ---- live website verification (real evidence) ----
    if site:
        if not site.get("ok"):
            add("Website didn't load — reach out by phone or DM instead", "verified", 0)
        else:
            chat = site.get("chat")
            if chat:
                if service_key == "chatbot":
                    add(f"Already runs {chat} chat — pitch as an upgrade to real AI", "verified", -10)
                elif service_key == "rag_support" and chat in ("Intercom", "Zendesk", "Drift", "Freshchat", "Chatwoot"):
                    add(f"Runs {chat} — clean integration point for an AI support agent", "verified", 10)
                else:
                    add(f"Already runs {chat} chat on their site", "verified", 0)
            elif service_key == "chatbot":
                add("No live chat widget found on their website — the gap is real", "verified", 12)
            elif service_key in ("voice", "dm"):
                add("No live chat on site — visitors have no instant-answer path", "verified", 6)

            booking = site.get("booking")
            if booking:
                if service_key in ("chatbot", "voice"):
                    add(f"Has {booking} — the AI can book straight into it", "verified", 8)
                else:
                    add(f"Has {booking} booking", "verified", 2)
            elif service_key in ("chatbot", "voice"):
                add("No online booking system found — pitch auto-booking as the differentiator", "verified", 4)

            n_sp = site.get("support_pages") or 0
            if service_key == "email_support" and n_sp >= 2:
                add(f"Site has {n_sp} help/FAQ/support pages — real question volume", "verified", 10)
            elif n_sp:
                add(f"Site has {n_sp} help/support pages", "verified", 2)

    score = max(10, min(95, score))
    label = "Strong fit" if score >= 75 else "Good fit" if score >= 58 else "Warm lead"
    return score, label, reasons


def build_dm_block(lead, service_key, cat_key, city, site=None):
    cat = CATEGORIES[cat_key]
    svc = SERVICES[service_key]
    roles = list(cat["dm_roles"])
    for r in svc.get("dm_extra_roles", []):
        if r not in roles:
            roles.append(r)

    q_people = f'"{lead["name"]}" {roles[0] if roles else "owner"} {city}'
    q_google = f'"{lead["name"]}" "{city}" (owner OR manager OR director OR "founded by")'
    q_fb = f'{lead["name"]} {city}'
    q_gbp = f'"{lead["name"]}" {city}'

    links = [
        {"label": "LinkedIn search", "url": "https://www.linkedin.com/search/results/people/?keywords="
          + urllib.parse.quote(q_people),
         "tip": "Filter by your city — first result is usually the owner/manager"},
        {"label": "Google search", "url": "https://www.google.com/search?q="
          + urllib.parse.quote(q_google),
         "tip": "Look for \"About the team\" pages, press mentions, or the owner's name"},
        {"label": "Facebook search", "url": "https://www.facebook.com/search/top?q="
          + urllib.parse.quote(q_fb),
         "tip": "Owners of local businesses often post from their personal profiles"},
        {"label": "Google reviews — 10-sec check", "url": "https://www.google.com/search?tbm=lcl&q="
          + urllib.parse.quote(q_gbp),
         "tip": "Count the reviews and check if the owner responds to any. "
                "Many reviews + zero owner responses = send the pitch with the exact count."},
    ]
    if lead.get("website"):
        links.insert(0, {"label": "Website (Team/About page)", "url": lead["website"],
                         "tip": "The fastest free route: most local sites list their team"})
    if svc.get("linkedin_search"):
        links.append({"label": "B2B LinkedIn company search", "url":
                      "https://www.linkedin.com/search/results/people/?keywords="
                      + urllib.parse.quote(svc["linkedin_search"]),
                      "tip": "For bigger targets: filter by company size 50–500 employees"})

    if lead.get("contact_person"):
        first_line = f"OSM already lists a contact person: **{lead['contact_person']}** — verify, then reach out."
    else:
        first_line = f"Most likely decision-maker: **{roles[0]}**{(' (also consider: ' + ', '.join(roles[1:]) + ')') if len(roles) > 1 else ''}."
    if site and site.get("person"):
        p = site["person"][0]
        first_line += (f" Possible name found on their website: **{p['name']}** ({p['title']}) — "
                       "verify before you send.")
    return first_line, links


def fill_pitch(template, lead, service_key, cat_key, city):
    svc = SERVICES[service_key]
    cat = CATEGORIES[cat_key]
    person = lead.get("contact_person")
    m = {
        "{business}": lead["name"],
        "{city}": city,
        "{first}": person if person else ("the " + lead["name"] + " team"),
        "{website}": lead.get("website") or "your website",
        "{phone}": lead.get("phone") or "[phone number]",
        "{category}": cat.get("short") or cat["label"].lower(),
        "{role}": cat["dm_roles"][0] if cat["dm_roles"] else "owner",
        "{you}": "[Your name]",
        # "[REVIEW COUNT]" left intentionally for the user to fill from Google Maps
    }
    out = template
    for k, v in m.items():
        out = out.replace(k, str(v))
    return out


def find_leads(body):
    city = (body.get("city") or "").strip()
    cat_key = body.get("category") or "dentist"
    svc_key = body.get("service") or "chatbot"
    try:
        radius = int(body.get("radius") or 5)
    except (TypeError, ValueError):
        radius = 5
    radius = max(1, min(50, radius))

    if cat_key not in CATEGORIES:
        raise ValueError(f"Unknown category: {cat_key}")
    if svc_key not in SERVICES:
        raise ValueError(f"Unknown service: {svc_key}")
    if not city:
        raise ValueError("Please enter a city.")

    geo = geocode(city)
    if not geo:
        raise ValueError(f"Couldn't find the city \"{city}\". Try a different spelling (e.g. \"London\", \"Lagos\", \"Austin\").")

    query = build_query(geo["lat"], geo["lon"], radius * 1000, CATEGORIES[cat_key]["filters"])
    data = overpass(query)
    raw = parse_elements(data.get("elements", []))[:40]

    # live-verify the top few websites in parallel (only for services where the site matters)
    SITE_CHECK_SERVICES = {"chatbot", "voice", "dm", "rag_support", "email_support"}
    sites_by_id = {}
    if svc_key in SITE_CHECK_SERVICES:
        to_check = [l for l in raw if l.get("website")][:8]
        if to_check:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for result, lead in zip(ex.map(site_check, to_check), to_check):
                    sites_by_id[id(lead)] = result

    leads = []
    for lead in raw:
        site = sites_by_id.get(id(lead))
        score, label, reasons = fit_score(lead, svc_key, cat_key, site)
        dm_line, dm_links = build_dm_block(lead, svc_key, cat_key, geo["name"], site)
        leads.append({
            **lead,
            "fit": score,
            "fit_label": label,
            "reasons": reasons,
            "dm_line": dm_line,
            "dm_links": dm_links,
            "email_subject": fill_pitch(SERVICES[svc_key]["email_subject"], lead, svc_key, cat_key, geo["name"]),
            "email_body": fill_pitch(SERVICES[svc_key]["email_body"], lead, svc_key, cat_key, geo["name"]),
            "dm_pitch": fill_pitch(SERVICES[svc_key]["dm_text"], lead, svc_key, cat_key, geo["name"]),
        })

    leads.sort(key=lambda x: -x["fit"])
    return {
        "city": geo["name"],
        "city_display": geo["display"],
        "category": CATEGORIES[cat_key]["label"],
        "service": SERVICES[svc_key]["label"],
        "radius": radius,
        "count": len(leads),
        "leads": leads,
    }

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "AIOutreachFinder/1.0"

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/meta":
            self._json({
                "categories": [
                    {"key": k, "label": v["label"], "note": v["note"]} for k, v in CATEGORIES.items()
                ],
                "services": [
                    {"key": k, "label": v["label"], "tier": v["tier"], "b2b": v.get("b2b", False)}
                    for k, v in SERVICES.items()
                ],
            })
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        try:
            if path == "/api/leads":
                self._json(find_leads(body))
            elif path == "/api/suggest":
                self._json({"results": suggest_cities((body.get("q") or "").strip())})
            else:
                self._json({"error": "not found"}, 404)
        except RuntimeError as e:
            self._json({"error": str(e)}, 502)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"Something went wrong: {e}"}, 500)


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"AI Outreach Finder running on http://0.0.0.0:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
