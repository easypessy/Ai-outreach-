import json, urllib.request

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())

base = "http://127.0.0.1:8321/api/leads"

tests = [
    ("Lagos dentists / voice", {"city": "Lagos", "category": "dentist", "service": "voice", "radius": 5}),
    ("Austin restaurants / reviews", {"city": "Austin", "category": "restaurant", "service": "reviews", "radius": 3}),
    ("Lagos law firms / doc_processing", {"city": "Lagos", "category": "law", "service": "doc_processing", "radius": 8}),
    ("London gyms / dm", {"city": "London", "category": "gym", "service": "dm", "radius": 4}),
]

for label, body in tests:
    print("=" * 70)
    print(label)
    try:
        d = post(base, body)
        print(f"  count={d['count']}  city={d['city']}  radius={d['radius']}km")
        for l in d["leads"][:6]:
            print(f"  - [{l['fit']} {l['fit_label']}] {l['name']}")
            print(f"      addr: {l['address'] or '-'} | phone: {l['phone'] or '-'} | site: {l['website'] or '-'} | fb: {l['facebook'] or '-'} | ig: {l['instagram'] or '-'}")
    except Exception as e:
        print("  ERROR:", e)

print("=" * 70)
print("FULL SAMPLE LEAD (first from test 1 style) - checking pitch quality")
d = post(base, {"city": "Lagos", "category": "dentist", "service": "voice", "radius": 5})
if d["leads"]:
    l = d["leads"][0]
    print("NAME:", l["name"])
    print("DM LINE:", l["dm_line"])
    print("DM LINKS:")
    for a in l["dm_links"]:
        print("   ", a["label"], "->", a["url"])
    print("\nEMAIL SUBJECT:", l["email_subject"])
    print("\nEMAIL BODY:\n", l["email_body"])
    print("\nDM PITCH:\n", l["dm_pitch"])
