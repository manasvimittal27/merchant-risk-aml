"""
Synthetic data for a payment aggregator's merchant-risk team.

All names, merchants and the watchlist are invented. Bad merchants are over-sampled so
every typology is visible; rates are not meant to be realistic.

Tables written to data/:
  merchants.csv         onboarding (KYC / CDD) record for each merchant
  directors.csv         one authorised signatory per merchant (name, DOB, nationality)
  watchlist.csv         invented sanctions / PEP list (name, DOB, nationality, list)
  transactions.csv      captured payments, Jan-Jun 2026
  refunds.csv           refunds, incl. whether they went back to the paying instrument
  chargebacks.csv       chargebacks with network, reason code, stage and outcome
  merchant_events.csv   settlement bank-account changes and website changes
  merchant_outcomes.csv ground truth after investigation (for scoring only)

Bad-merchant typologies
  mule_laundering         volume far above declared turnover, few payers, large amounts
                          clustered just under Rs 50,000, settlement account changed
  transaction_laundering  declares education/consulting/digital goods but processes
                          many tiny late-night payments from many payers (looks like
                          betting / illegal gaming)
  fake_store              new website with no policies; short sales burst, then a wave
                          of fraud and non-receipt chargebacks and refunds to other cards
  sanctions_match         signatory is a true match to the watchlist
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(exist_ok=True)

START, END = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-30 23:59:59")
N_DAYS = (END.normalize() - START).days + 1
N = 2_500

# category: (share, median ticket Rs, sigma, declared monthly turnover median Rs, P(card), night share)
CATS = {
    "apparel_ecommerce":   (0.20, 1_200, 0.7, 6_00_000, 0.45, 0.12),
    "electronics":         (0.10, 8_000, 0.8, 15_00_000, 0.55, 0.10),
    "education":           (0.10, 3_000, 0.9, 5_00_000, 0.35, 0.08),
    "travel":              (0.08, 9_000, 0.8, 20_00_000, 0.60, 0.12),
    "food_restaurants":    (0.17, 450, 0.5, 4_00_000, 0.25, 0.35),
    "healthcare":          (0.08, 1_500, 0.8, 5_00_000, 0.30, 0.08),
    "jewellery":           (0.04, 25_000, 0.9, 25_00_000, 0.55, 0.06),
    "digital_goods":       (0.10, 300, 0.6, 3_00_000, 0.40, 0.25),
    "consulting_services": (0.08, 15_000, 1.0, 8_00_000, 0.40, 0.05),
    "wholesale_b2b":       (0.05, 40_000, 0.7, 30_00_000, 0.20, 0.03),
}
CAT_NAMES = list(CATS)
CAT_P = np.array([c[0] for c in CATS.values()]); CAT_P /= CAT_P.sum()
HIGH_RISK_CATS = {"jewellery", "consulting_services", "digital_goods"}

FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Rohan", "Kavya", "Arjun", "Neha", "Karan", "Pooja",
         "Sanjay", "Meera", "Aditya", "Riya", "Manish", "Divya", "Suresh", "Ananya", "Rakesh", "Isha", "Deepak", "Tanvi",
         "Nikhil", "Shreya", "Varun", "Aisha", "Imran", "Farah", "Gurpreet", "Harleen", "Joseph", "Maria", "Ravi", "Lakshmi"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Shah", "Mehta", "Reddy", "Nair", "Iyer", "Rao", "Das",
        "Bose", "Khan", "Ali", "Kapoor", "Malhotra", "Agarwal", "Jain", "Chopra", "Joshi", "Pillai", "Menon", "Gill",
        "Dsouza", "Fernandes", "Mishra", "Pandey", "Yadav"]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Lucknow",
          "Indore", "Surat"]

# ----------------------------------------------------------------------------------- merchants
cat = rng.choice(CAT_NAMES, N, p=CAT_P)
onboard = START - pd.to_timedelta(rng.integers(30, 540, N), unit="D")
mid = np.array([f"M{20000 + i}" for i in range(N)])
truth = np.array([""] * N, dtype=object)

idx = rng.permutation(N)
k = 0
def take(n, allowed=None):
    global k
    out = []
    while len(out) < n:
        i = idx[k]; k += 1
        if allowed is None or cat[i] in allowed:
            out.append(i)
        else:
            idx_rest.append(i)
    return out
idx_rest = []
MULE = take(55, {"consulting_services", "electronics", "jewellery", "wholesale_b2b"})
TL = take(50, {"education", "consulting_services", "digital_goods"})
FAKE = take(60, {"apparel_ecommerce", "electronics"})
SANC = take(6)
for ids, lab in [(MULE, "mule_laundering"), (TL, "transaction_laundering"), (FAKE, "fake_store"), (SANC, "sanctions_match")]:
    truth[ids] = lab
bad = truth != ""

# Recent onboarding for most bad merchants
recent = np.isin(np.arange(N), MULE + TL + FAKE) & (rng.random(N) < 0.75)
onboard = onboard.to_numpy().copy()
onboard[recent] = (START + pd.to_timedelta(rng.integers(-60, 45, recent.sum()), unit="D")).to_numpy()
onboard = pd.to_datetime(onboard).normalize()

def p(good_p, bad_p):
    return np.where(bad & (truth != "sanctions_match"), rng.random(N) < bad_p, rng.random(N) < good_p)

website_age = np.where(bad & (truth != "sanctions_match"), rng.integers(5, 120, N), rng.integers(60, 3000, N))
website_age = np.where(~bad & (rng.random(N) < 0.10), rng.integers(5, 90, N), website_age)  # genuine new businesses
policies = ~p(0.08, 0.45)                       # refund/privacy/terms pages present
content_match = ~p(0.04, 0.0)
content_match[TL] = rng.random(len(TL)) < 0.45  # website often doesn't match declared business
content_match[MULE] = rng.random(len(MULE)) < 0.75
gst_ok = ~p(0.06, 0.35)
bank_name_match = ~p(0.03, 0.30)
biz_type = np.where(p(0.35, 0.70), "proprietorship", rng.choice(["pvt_ltd", "partnership", "llp"], N, p=[.6, .25, .15]))
docs_complete = ~p(0.05, 0.25)

declared = np.array([CATS[c][3] for c in cat]) / 4 * np.exp(0.6 * rng.standard_normal(N))
declared = (np.round(declared / 10_000) * 10_000).clip(min=50_000)

merchants = pd.DataFrame({
    "merchant_id": mid, "legal_name": [f"{rng.choice(LAST)} {rng.choice(['Enterprises','Traders','Solutions','Retail','Ventures','Services','Store','Labs'])}" for _ in range(N)],
    "category": cat, "business_type": biz_type, "city": rng.choice(CITIES, N),
    "onboard_date": onboard, "declared_monthly_turnover": declared.astype(int),
    "website_age_days": website_age, "website_has_policies": policies, "website_matches_category": content_match,
    "gst_verified": gst_ok, "bank_name_matches_entity": bank_name_match, "kyc_docs_complete": docs_complete,
})

# ----------------------------------------------------------------------------------- directors + watchlist
def dob():
    return (pd.Timestamp("1965-01-01") + pd.Timedelta(days=int(rng.integers(0, 12000)))).date()

directors = pd.DataFrame({
    "merchant_id": mid,
    "director_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(N)],
    "dob": [dob() for _ in range(N)],
    "nationality": np.where(rng.random(N) < 0.97, "IN", rng.choice(["AE", "GB", "SG", "US", "NP"], N)),
})

WL_FIRST = FIRST + ["Viktor", "Omar", "Hassan", "Dmitri", "Chen", "Abdul", "Yusuf", "Kareem", "Sergei", "Mehmet"]
WL_LAST = LAST + ["Volkov", "Rahimi", "Haddad", "Petrov", "Wei", "Karimov", "Nasser", "Orlov", "Demir", "Saleh"]
wl = pd.DataFrame({
    "watchlist_id": [f"W{9000 + i}" for i in range(400)],
    "name": [f"{rng.choice(WL_FIRST)} {rng.choice(WL_LAST)}" for _ in range(400)],
    "dob": [dob() for _ in range(400)],
    "nationality": rng.choice(["IN", "AE", "RU", "IR", "SY", "KP", "AF", "PK", "CN", "TR"], 400),
    "list_type": rng.choice(["sanctions", "pep"], 400, p=[0.6, 0.4]),
})
# True matches: signatory IS the listed person (name may be spelled slightly differently)
for j, i in enumerate(SANC):
    w = wl.iloc[j]
    nm = w["name"]
    if j % 2 == 1:   # spelling variant
        nm = nm.replace("a", "aa", 1) if "a" in nm else nm + "h"
    directors.loc[i, ["director_name", "dob", "nationality"]] = [nm, w["dob"], w["nationality"]]

# ----------------------------------------------------------------------------------- transactions
act_start = pd.Series(onboard).clip(lower=START)
act_days = ((END.normalize() - act_start).dt.days + 1).clip(lower=1).to_numpy()
med = np.array([CATS[c][1] for c in cat]); sig = np.array([CATS[c][2] for c in cat])
p_card = np.array([CATS[c][4] for c in cat]); night = np.array([CATS[c][5] for c in cat])

# daily rate implied by declared turnover, with genuine under-declaration for some
rate = declared / 30.4 / (med * np.exp(sig ** 2 / 2))
growth = np.where(~bad & (rng.random(N) < 0.08), rng.uniform(3, 5, N), rng.uniform(0.5, 1.3, N))  # under-declared turnover
rate = (rate * growth).clip(0.05, 15)
payer_pool = np.where(cat == "wholesale_b2b", rng.integers(8, 40, N), rng.integers(200, 5000, N))
b2b_like = ~bad & (cat != "wholesale_b2b") & (rng.random(N) < 0.03)    # genuine merchants with a few big clients
payer_pool = np.where(b2b_like, rng.integers(5, 25, N), payer_pool)

frames = []
def emit(i, n, t, amt, method, payer):
    frames.append(pd.DataFrame({"m": i, "ts": t, "amount": np.round(amt, 2), "method": method, "payer": payer}))

for i in range(N):
    lab = truth[i]
    if lab in ("", "sanctions_match"):
        n = rng.poisson(rate[i] * act_days[i])
        if n == 0:
            continue
        day = rng.integers(0, act_days[i], n)
        hour = np.where(rng.random(n) < night[i], rng.integers(22, 28, n) % 24, rng.integers(8, 22, n))
        t = act_start.iloc[i] + pd.to_timedelta(day, "D") + pd.to_timedelta(hour * 3600 + rng.integers(0, 3600, n), "s")
        amt = np.exp(np.log(med[i]) + sig[i] * rng.standard_normal(n)).clip(10)
        method = np.where(rng.random(n) < p_card[i], "card", rng.choice(["upi", "netbanking"], n, p=[.8, .2]))
        payer = [f"P{i}_{x}" for x in rng.integers(0, payer_pool[i], n)]
        emit(i, n, t, amt, method, payer)
    elif lab == "mule_laundering":
        # normal-looking first weeks, then large pass-through volume from a handful of payers
        s0 = act_start.iloc[i] + pd.Timedelta(days=int(rng.integers(10, 50)))
        days_left = max((END - s0).days, 5)
        n = int(rng.integers(120, 420))
        day = rng.integers(0, days_left, n)
        t = s0 + pd.to_timedelta(day, "D") + pd.to_timedelta(rng.integers(0, 86400, n), "s")
        amt = np.where(rng.random(n) < 0.6, rng.uniform(45_000, 49_999, n), np.round(rng.uniform(5_000, 200_000, n), -3))
        method = rng.choice(["netbanking", "upi", "card"], n, p=[.5, .35, .15])
        payer = [f"P{i}_{x}" for x in rng.integers(0, int(rng.integers(4, 25)), n)]
        emit(i, n, t, amt, method, payer)
        # thin genuine-looking trickle before that
        n2 = int(rng.integers(5, 25))
        t2 = act_start.iloc[i] + pd.to_timedelta(rng.integers(0, 10, n2), "D") + pd.to_timedelta(rng.integers(32400, 72000, n2), "s")
        emit(i, n2, t2, np.exp(np.log(med[i]) + 0.5 * rng.standard_normal(n2)), np.array(["upi"] * n2), [f"P{i}_g{x}" for x in range(n2)])
    elif lab == "transaction_laundering":
        n = int(rng.integers(1200, 3500))
        day = rng.integers(0, act_days[i], n)
        hour = np.where(rng.random(n) < 0.7, rng.integers(22, 28, n) % 24, rng.integers(10, 22, n))
        t = act_start.iloc[i] + pd.to_timedelta(day, "D") + pd.to_timedelta(hour * 3600 + rng.integers(0, 3600, n), "s")
        amt = rng.choice([100, 200, 250, 500, 1000, 1500, 2000], n) + 0.0
        payer = [f"P{i}_{x}" for x in rng.integers(0, int(rng.integers(800, 3000)), n)]
        emit(i, n, t, amt, rng.choice(["upi", "card"], n, p=[.9, .1]), payer)
    elif lab == "fake_store":
        s0 = act_start.iloc[i] + pd.Timedelta(days=int(rng.integers(0, 60)))
        n = int(rng.integers(150, 600))
        burst = int(rng.integers(20, 45))
        t = s0 + pd.to_timedelta(rng.integers(0, burst, n), "D") + pd.to_timedelta(rng.integers(32400, 86400, n), "s")
        amt = np.exp(np.log(med[i] * 1.6) + 0.5 * rng.standard_normal(n))
        method = np.where(rng.random(n) < 0.8, "card", "upi")
        payer = [f"P{i}_{x}" for x in rng.integers(0, n, n)]
        emit(i, n, t, amt, method, payer)

tx = pd.concat(frames, ignore_index=True)
tx = tx[(tx["ts"] >= START) & (tx["ts"] <= END)].sort_values("ts").reset_index(drop=True)
tx.insert(0, "txn_id", [f"T{30_000_000 + j}" for j in range(len(tx))])
tx["merchant_id"] = mid[tx["m"]]

# ----------------------------------------------------------------------------------- refunds
ref_rows = []
base_ref = np.where(cat == "apparel_ecommerce", 0.06, np.where(cat == "travel", 0.08, 0.02))
for i, g in tx.groupby("m"):
    lab = truth[i]
    pr = 0.35 if lab == "fake_store" else base_ref[i]
    sel = g[rng.random(len(g)) < pr]
    for r in sel.itertuples():
        diff = rng.random() < (0.55 if lab == "fake_store" else 0.01)
        ref_rows.append((r.txn_id, mid[i], r.ts + pd.Timedelta(days=int(rng.integers(1, 12))),
                         round(r.amount * (1 if rng.random() < .8 else rng.uniform(.3, .9)), 2), not diff))
refunds = pd.DataFrame(ref_rows, columns=["txn_id", "merchant_id", "refund_ts", "amount", "to_original_instrument"])
refunds = refunds[refunds["refund_ts"] <= END].sort_values("refund_ts").reset_index(drop=True)
refunds.insert(0, "refund_id", [f"R{800_000 + j}" for j in range(len(refunds))])

# ----------------------------------------------------------------------------------- chargebacks (card only)
FRAUD_CODES = [("visa", "10.4", "Other fraud, card-absent"), ("mastercard", "4837", "No cardholder authorisation")]
NONFRAUD = [("visa", "13.1", "Merchandise/services not received"), ("visa", "13.3", "Not as described"),
            ("visa", "12.6", "Duplicate processing"), ("mastercard", "4855", "Goods or services not provided"),
            ("mastercard", "4834", "Point-of-interaction error")]
TECH = {"12.6", "4834"}
cb_rows = []
cards = tx[tx["method"] == "card"]
for i, g in cards.groupby("m"):
    lab = truth[i]
    if lab == "fake_store":
        rate_f, rate_n = rng.uniform(0.05, 0.12), rng.uniform(0.04, 0.10)
    elif lab == "mule_laundering":
        rate_f, rate_n = 0.004, 0.002
    elif lab == "transaction_laundering":
        rate_f, rate_n = 0.006, 0.004
    else:
        rate_f = 0.0012 * (3 if rng.random() < 0.05 else 1)
        rate_n = (0.008 if cat[i] == "travel" else 0.002)
    for r in g.itertuples():
        u = rng.random()
        if u < rate_f:
            net, code, desc = FRAUD_CODES[rng.integers(0, 2)]
        elif u < rate_f + rate_n:
            net, code, desc = NONFRAUD[rng.integers(0, len(NONFRAUD))]
        else:
            continue
        cb_date = r.ts + pd.Timedelta(days=int(rng.integers(7, 60)))
        if cb_date > END:
            continue
        genuine = lab in ("", "sanctions_match")
        represented = rng.random() < (0.6 if genuine else 0.1)
        if not represented:
            stage, outcome = "first_chargeback", "accepted_by_merchant"
        else:
            won = rng.random() < (0.5 if code not in TECH else 0.7)
            if won:
                stage, outcome = "representment", "won_by_merchant"
            elif rng.random() < 0.15:
                stage, outcome = "arbitration", rng.choice(["won_by_merchant", "lost_by_merchant"], p=[.35, .65])
            else:
                stage, outcome = "pre_arbitration", "lost_by_merchant"
        cb_rows.append((r.txn_id, mid[i], cb_date.normalize(), net, code, desc,
                        "fraud" if code in ("10.4", "4837") else ("technical" if code in TECH else "consumer_dispute"),
                        r.amount, stage, outcome))
cbs = pd.DataFrame(cb_rows, columns=["txn_id", "merchant_id", "cb_date", "network", "reason_code", "reason_desc",
                                     "reason_group", "amount", "final_stage", "outcome"])
cbs = cbs.sort_values("cb_date").reset_index(drop=True)
cbs.insert(0, "chargeback_id", [f"CB{60_000 + j}" for j in range(len(cbs))])

# ----------------------------------------------------------------------------------- merchant events
ev = []
for i in MULE:
    if rng.random() < 0.7:
        ev.append((mid[i], act_start.iloc[i] + pd.Timedelta(days=int(rng.integers(5, 40))), "settlement_account_change"))
for i in np.where(~bad)[0][rng.random((~bad).sum()) < 0.04]:
    ev.append((mid[i], START + pd.Timedelta(days=int(rng.integers(0, N_DAYS))), "settlement_account_change"))
for i in rng.choice(N, 150, replace=False):
    ev.append((mid[i], START + pd.Timedelta(days=int(rng.integers(0, N_DAYS))), "website_change"))
events = pd.DataFrame(ev, columns=["merchant_id", "event_date", "event_type"])
events = events[(events["event_date"] >= START) & (events["event_date"] <= END)].sort_values("event_date")

outcomes = pd.DataFrame({"merchant_id": mid, "confirmed_typology": truth})
outcomes = outcomes[outcomes["confirmed_typology"] != ""]

# ----------------------------------------------------------------------------------- write
merchants.to_csv(OUT / "merchants.csv", index=False)
directors.to_csv(OUT / "directors.csv", index=False)
wl.to_csv(OUT / "watchlist.csv", index=False)
tx[["txn_id", "merchant_id", "ts", "amount", "method", "payer"]].rename(columns={"payer": "payer_id"}).to_csv(OUT / "transactions.csv", index=False)
refunds.to_csv(OUT / "refunds.csv", index=False)
cbs.to_csv(OUT / "chargebacks.csv", index=False)
events.to_csv(OUT / "merchant_events.csv", index=False)
outcomes.to_csv(OUT / "merchant_outcomes.csv", index=False)

print(f"merchants {N:,} | bad {bad.sum()} {pd.Series(truth[bad]).value_counts().to_dict()}")
print(f"transactions {len(tx):,} | Rs {tx['amount'].sum()/1e7:,.1f} cr | refunds {len(refunds):,} | chargebacks {len(cbs):,} | events {len(events):,}")
