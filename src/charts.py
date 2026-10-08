"""Report charts from outputs/ into outputs/charts/."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"; CH = OUT / "charts"; CH.mkdir(parents=True, exist_ok=True)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#c9c8c2"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True, "legend.frameon": False,
})
res = json.loads((OUT / "results.json").read_text())

# 1. Rules: merchants alerted, split by confirmed bad vs genuine
sc = pd.read_csv(OUT / "monitoring_rule_scorecard.csv").iloc[::-1]
labels = sc["rule"].str.replace("_", " ").str.replace(r"^(TM\d) ", r"\1  ", regex=True)
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.barh(labels, sc["bad_merchants_alerted"], color=BLUE, height=0.6, label="Confirmed bad merchant")
ax.barh(labels, sc["false_positive_merchants"], left=sc["bad_merchants_alerted"] + 1.5, color=NEUTRAL, height=0.6,
        label="Genuine merchant (false positive)")
for y, (b, f, p) in enumerate(zip(sc["bad_merchants_alerted"], sc["false_positive_merchants"], sc["precision"])):
    ax.text(b + f + 5, y, f"{p:.0%} precise", va="center", fontsize=9, color=INK2)
ax.set_xlabel("Merchants alerted, Jan–Jun 2026")
ax.set_xlim(0, 320)
ax.grid(axis="y", visible=False)
ax.set_title("TM1 turnover mismatch creates most false positives")
ax.legend(loc="lower right", fontsize=9)
fig.tight_layout(); fig.savefig(CH / "rule_precision.png", dpi=180); plt.close(fig)

# 2. Sanctions screening funnel
s = res["sanctions"]
steps = [("Signatories screened", s["directors_screened"]), ("Name-only fuzzy matches", s["name_only_alerts"]),
         ("Need analyst review\n(DOB or nationality also match)", s["after_identifiers_escalated"] + s["partial_review"]),
         ("Escalated: name + DOB + nationality", s["after_identifiers_escalated"])]
fig, ax = plt.subplots(figsize=(9, 3.4))
ys = range(len(steps))[::-1]
for y, (lab, v) in zip(ys, steps):
    ax.barh(y, v, color=BLUE if v == s["after_identifiers_escalated"] else NEUTRAL, height=0.6)
    ax.text(v + 25, y, f"{v:,}", va="center", fontsize=10, color=INK)
ax.set_yticks(list(ys), [l for l, _ in steps])
ax.set_xlim(0, 2900); ax.grid(axis="y", visible=False)
ax.set_title(f"DOB and nationality checks cut {s['name_only_alerts']} name matches to {s['after_identifiers_escalated'] + s['partial_review']} reviews")
fig.tight_layout(); fig.savefig(CH / "sanctions_screening.png", dpi=180); plt.close(fig)

# 3. Onboarding rating: bad-merchant rate per tier
r = pd.read_csv(OUT / "onboarding_rating_performance.csv")
fig, ax = plt.subplots(figsize=(8, 3.2))
ax.barh(r["onboarding_rating"][::-1], r["bad_rate"][::-1], color=[BLUE, NEUTRAL, NEUTRAL], height=0.55)
for y, (rt, n, b) in enumerate(zip(r["bad_rate"][::-1], r["merchants"][::-1], r["bad"][::-1])):
    ax.text(rt + 0.015, y, f"{rt:.1%}  ({b} of {n:,} merchants)", va="center", fontsize=9)
ax.set_xlim(0, 1.15)
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
ax.set_xlabel("Share of merchants later confirmed bad"); ax.grid(axis="y", visible=False)
ax.set_title("Onboarding rating separates risk: High tier is 88% bad, Low tier 1.6%")
fig.tight_layout(); fig.savefig(CH / "onboarding_rating.png", dpi=180); plt.close(fig)

# 4. Escalation queue by priority
q = pd.read_csv(OUT / "escalation_priority_performance.csv")
fig, ax = plt.subplots(figsize=(8, 3))
q = q.iloc[::-1]
ax.barh(q["priority"], q["bad"], color=BLUE, height=0.55, label="Confirmed bad")
ax.barh(q["priority"], q["cases"] - q["bad"], left=q["bad"] + 1, color=NEUTRAL, height=0.55, label="Genuine")
for y, (c, p) in enumerate(zip(q["cases"], q["precision"])):
    ax.text(c + 3, y, f"{c} cases, {p:.0%} bad", va="center", fontsize=9)
ax.set_xlim(0, 230); ax.grid(axis="y", visible=False)
ax.set_title("Priority tiers send every confirmed bad merchant to P1 or P2")
ax.legend(loc="upper right", fontsize=9)
fig.tight_layout(); fig.savefig(CH / "escalation_queue.png", dpi=180); plt.close(fig)
print(sorted(p.name for p in CH.glob("*.png")))
