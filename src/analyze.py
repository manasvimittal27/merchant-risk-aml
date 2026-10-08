"""
Merchant risk & AML analysis for a payment aggregator.

  1. Onboarding risk rating   explainable points score -> Low / Medium / High (High = EDD)
  2. Sanctions / PEP screening  fuzzy name match, then secondary identifiers (DOB, nationality)
  3. Transaction monitoring   7 SQL rules (sql/monitoring_rules.sql), scored per rule
  4. Escalation queue         one case per merchant, plain-language reasons, recommended action
  5. Chargebacks              reason codes, stages, merchant fraud-chargeback ratios

Outputs go to outputs/. Ground truth (merchant_outcomes.csv) is used only for scoring.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parents[1]
DATA, SQL, OUT = ROOT / "data", ROOT / "sql", ROOT / "outputs"
OUT.mkdir(exist_ok=True)
END = pd.Timestamp("2026-06-30 23:59:59")

con = duckdb.connect()
for t in ["merchants", "directors", "watchlist", "transactions", "refunds", "chargebacks", "merchant_events", "merchant_outcomes"]:
    con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{DATA / (t + '.csv')}')")
con.execute("ALTER TABLE transactions ALTER ts TYPE TIMESTAMP")
con.execute("ALTER TABLE refunds ALTER refund_ts TYPE TIMESTAMP")
con.execute("ALTER TABLE chargebacks ALTER cb_date TYPE TIMESTAMP")
con.execute("ALTER TABLE merchant_events ALTER event_date TYPE TIMESTAMP")

m = con.execute("SELECT * FROM merchants").df()
d = con.execute("SELECT * FROM directors").df()
wl = con.execute("SELECT * FROM watchlist").df()
truth = con.execute("SELECT * FROM merchant_outcomes").df().set_index("merchant_id")["confirmed_typology"]
m["typology"] = m["merchant_id"].map(truth).fillna("")
m["is_bad"] = m["typology"] != ""
res = {}

# ------------------------------------------------------------------------- 2. sanctions screening
names = wl["name"].tolist()
rows = []
for r in d.itertuples():
    for nm, score, j in process.extract(r.director_name, names, scorer=fuzz.token_sort_ratio, limit=5, score_cutoff=85):
        w = wl.iloc[j]
        rows.append({"merchant_id": r.merchant_id, "director_name": r.director_name, "watchlist_id": w.watchlist_id,
                     "watchlist_name": nm, "name_score": round(score, 1), "list_type": w.list_type,
                     "dob_match": str(r.dob) == str(w.dob), "nationality_match": r.nationality == w.nationality})
hits = pd.DataFrame(rows)
hits["disposition"] = np.where(hits["dob_match"] & hits["nationality_match"], "escalate: probable true match",
                       np.where(hits["dob_match"] | hits["nationality_match"], "review: partial identifier match",
                                "auto-close with rationale: identifiers differ"))
hits.to_csv(OUT / "sanctions_screening_hits.csv", index=False)
true_sanc = set(m.loc[m["typology"] == "sanctions_match", "merchant_id"])
esc = hits[hits["disposition"].str.startswith("escalate")]
res["sanctions"] = {
    "directors_screened": len(d),
    "name_only_alerts": int(hits["merchant_id"].nunique()),
    "after_identifiers_escalated": int(esc["merchant_id"].nunique()),
    "partial_review": int(hits.loc[hits["disposition"].str.startswith("review"), "merchant_id"].nunique()),
    "true_matches": len(true_sanc),
    "true_matches_escalated": len(true_sanc & set(esc["merchant_id"])),
    "true_matches_exact_name": int(hits[hits["merchant_id"].isin(true_sanc) & (hits["name_score"] == 100)]["merchant_id"].nunique()),
}

# ------------------------------------------------------------------------- 1. onboarding risk rating
RISK_CATS = {"jewellery", "consulting_services", "digital_goods"}
pts = pd.DataFrame(index=m.index)
pts["high_risk_category"] = m["category"].isin(RISK_CATS) * 2
pts["website_under_90_days"] = (m["website_age_days"] < 90) * 2
pts["no_policy_pages"] = (~m["website_has_policies"]) * 2
pts["website_mismatch"] = (~m["website_matches_category"]) * 3
pts["gst_not_verified"] = (~m["gst_verified"]) * 1
pts["bank_name_mismatch"] = (~m["bank_name_matches_entity"]) * 2
pts["docs_incomplete"] = (~m["kyc_docs_complete"]) * 1
pts["proprietorship"] = (m["business_type"] == "proprietorship") * 1
m["onboarding_score"] = pts.sum(axis=1)
m["onboarding_reasons"] = pts.apply(lambda r: ", ".join(k.replace("_", " ") for k, v in r.items() if v), axis=1)
m["onboarding_rating"] = pd.cut(m["onboarding_score"], [-1, 3, 6, 99], labels=["Low", "Medium", "High"]).astype(str)
m.loc[m["merchant_id"].isin(esc["merchant_id"]), "onboarding_rating"] = "High"   # screening hit overrides
rat = m.groupby("onboarding_rating").agg(merchants=("merchant_id", "size"), bad=("is_bad", "sum")).reindex(["Low", "Medium", "High"])
rat["bad_rate"] = (rat["bad"] / rat["merchants"]).round(3)
rat["share_of_all_bad"] = (rat["bad"] / m["is_bad"].sum()).round(3)
rat.to_csv(OUT / "onboarding_rating_performance.csv")
by_typ = pd.crosstab(m.loc[m["is_bad"], "typology"], m.loc[m["is_bad"], "onboarding_rating"]).reindex(columns=["Low", "Medium", "High"], fill_value=0)
by_typ.to_csv(OUT / "onboarding_rating_by_typology.csv")
res["onboarding"] = {"table": rat.reset_index().to_dict("records"), "by_typology": by_typ.to_dict("index")}

# ------------------------------------------------------------------------- 3. transaction monitoring
con.execute((SQL / "monitoring_rules.sql").read_text())
RULES = {
    "TM1_turnover_mismatch":       ("tm1_turnover_mismatch",       ["mule_laundering", "transaction_laundering"]),
    "TM2_structuring":             ("tm2_structuring",             ["mule_laundering"]),
    "TM3_payer_concentration":     ("tm3_payer_concentration",     ["mule_laundering"]),
    "TM4_refund_other_instrument": ("tm4_refund_other_instrument", ["fake_store"]),
    "TM5_fraud_chargeback_ratio":  ("tm5_fraud_chargeback_ratio",  ["fake_store"]),
    "TM6_business_model_mismatch": ("tm6_business_model_mismatch", ["transaction_laundering"]),
    "TM7_account_change_surge":    ("tm7_account_change_surge",    ["mule_laundering"]),
}
vol = con.execute("SELECT merchant_id, ts, amount FROM transactions").df()
first_bad_ts = vol[vol["merchant_id"].isin(truth.index)].groupby("merchant_id")["ts"].min()

alerts_all, score_rows = [], []
for rule, (view, targets) in RULES.items():
    a = con.execute(f"SELECT * FROM {view}").df()
    a["alert_ts"] = pd.to_datetime(a["alert_ts"])
    alerts_all.append(a)
    first = a.sort_values("alert_ts").groupby("merchant_id", as_index=False).first()
    first["typology"] = first["merchant_id"].map(truth).fillna("")
    tgt = set(m.loc[m["typology"].isin(targets), "merchant_id"])
    caught_tgt = tgt & set(first["merchant_id"])
    lag = (first.set_index("merchant_id").loc[list(caught_tgt), "alert_ts"] - first_bad_ts.loc[list(caught_tgt)]).dt.days
    score_rows.append({
        "rule": rule, "target_typologies": ", ".join(targets),
        "merchants_alerted": len(first), "bad_merchants_alerted": int((first["typology"] != "").sum()),
        "false_positive_merchants": int((first["typology"] == "").sum()),
        "precision": round((first["typology"] != "").mean(), 3) if len(first) else 0,
        "target_merchants": len(tgt), "target_caught": len(caught_tgt),
        "target_recall": round(len(caught_tgt) / len(tgt), 3) if tgt else 0,
        "median_days_to_alert": float(lag.median()) if len(lag) else None,
    })
scores = pd.DataFrame(score_rows)
scores.to_csv(OUT / "monitoring_rule_scorecard.csv", index=False)
alerts = pd.concat(alerts_all, ignore_index=True)

# Value processed by bad merchants before vs after their first alert (exposure a settlement hold would stop)
first_any = alerts.groupby("merchant_id")["alert_ts"].min()
bad_vol = vol[vol["merchant_id"].isin(truth.index)].copy()
bad_vol["first_alert"] = bad_vol["merchant_id"].map(first_any)
bad_vol["after_alert"] = bad_vol["first_alert"].notna() & (bad_vol["ts"] >= bad_vol["first_alert"])
bad_vol["typology"] = bad_vol["merchant_id"].map(truth)
exp = bad_vol.groupby("typology").apply(lambda g: pd.Series({
    "merchants": g["merchant_id"].nunique(),
    "caught": g.loc[g["first_alert"].notna(), "merchant_id"].nunique(),
    "volume_rs": g["amount"].sum(),
    "volume_after_alert_rs": g.loc[g["after_alert"], "amount"].sum()}), include_groups=False)
exp["share_stoppable"] = (exp["volume_after_alert_rs"] / exp["volume_rs"]).round(3)
exp.round({"merchants": 0, "caught": 0, "volume_rs": 0, "volume_after_alert_rs": 0}).to_csv(OUT / "exposure_by_typology.csv")

# ------------------------------------------------------------------------- 4. escalation queue
RULE_WEIGHT = {"TM1_turnover_mismatch": 2, "TM2_structuring": 3, "TM3_payer_concentration": 2,
               "TM4_refund_other_instrument": 3, "TM5_fraud_chargeback_ratio": 3,
               "TM6_business_model_mismatch": 3, "TM7_account_change_surge": 3}
a1 = alerts.sort_values("alert_ts").groupby(["merchant_id", "rule_id"], as_index=False).first()
a1["w"] = a1["rule_id"].map(RULE_WEIGHT)
case = a1.groupby("merchant_id").agg(rules_hit=("rule_id", "nunique"), tm_points=("w", "sum"),
                                     first_alert=("alert_ts", "min"),
                                     reasons=("reason", lambda s: " | ".join(s)),
                                     rules=("rule_id", lambda s: ", ".join(sorted(s)))).reset_index()
case = case.merge(m[["merchant_id", "legal_name", "category", "onboarding_rating", "onboarding_score", "typology"]], on="merchant_id")
case["priority_score"] = case["tm_points"] + case["onboarding_score"].clip(upper=6) / 2
case["priority"] = pd.cut(case["priority_score"], [-1, 3.9, 6.9, 99], labels=["P3 review", "P2 EDD", "P1 urgent"]).astype(str)

def action(r):
    if "TM2" in r.rules or "TM7" in r.rules or ("TM3" in r.rules and "TM1" in r.rules):
        return "Hold settlements; EDD on source of funds; consider STR to FIU-IND"
    if "TM6" in r.rules:
        return "Hold settlements; verify actual business (test purchase, site review); offboard if mismatch confirmed"
    if "TM5" in r.rules or "TM4" in r.rules:
        return "Apply rolling reserve; request delivery proof; review refunds and chargebacks"
    return "Request turnover proof (GST returns, bank statements); update risk profile"
case["recommended_action"] = case.apply(action, axis=1)
case = case.sort_values(["priority_score", "first_alert"], ascending=[False, True])
case.drop(columns=["typology"]).to_csv(OUT / "escalation_queue.csv", index=False)

pq = case.groupby("priority").agg(cases=("merchant_id", "size"), bad=("typology", lambda s: (s != "").sum()))
pq["precision"] = (pq["bad"] / pq["cases"]).round(3)
pq = pq.reindex(["P1 urgent", "P2 EDD", "P3 review"])
pq.to_csv(OUT / "escalation_priority_performance.csv")

monitored_bad = m[m["typology"].isin(["mule_laundering", "transaction_laundering", "fake_store"])]
caught = set(case["merchant_id"])
res["monitoring"] = {
    "merchants_alerted": len(case), "bad_caught": int(case["typology"].ne("").sum()),
    "behavioural_bad_total": len(monitored_bad), "behavioural_bad_caught": len(set(monitored_bad["merchant_id"]) & caught),
    "false_positive_merchants": int(case["typology"].eq("").sum()),
    "priority": pq.reset_index().to_dict("records"),
    "exposure": exp.round({"volume_rs": 0, "volume_after_alert_rs": 0}).reset_index().to_dict("records"),
    "alerts_per_week": round(len(case) / 26, 1),
}

# ------------------------------------------------------------------------- 5. chargebacks
cb = con.execute("SELECT * FROM chargebacks").df()
cb["typology"] = cb["merchant_id"].map(truth).fillna("")
codes = cb.groupby(["network", "reason_code", "reason_desc", "reason_group"]).agg(
    chargebacks=("chargeback_id", "size"), amount_rs=("amount", "sum")).reset_index().sort_values("chargebacks", ascending=False)
codes.to_csv(OUT / "chargebacks_by_reason_code.csv", index=False)
stage = cb.groupby(["final_stage", "outcome"]).size().rename("chargebacks").reset_index()
stage.to_csv(OUT / "chargebacks_by_stage.csv", index=False)
fraud_cb = cb[cb["reason_group"] == "fraud"]
rep = cb[cb["final_stage"] != "first_chargeback"]
res["chargebacks"] = {
    "total": len(cb), "fraud_coded": len(fraud_cb),
    "fraud_share_from_fake_stores": round((fraud_cb["typology"] == "fake_store").mean(), 3),
    "fake_store_merchants": int((m["typology"] == "fake_store").sum()),
    "represented": len(rep), "represented_won": int((rep["outcome"] == "won_by_merchant").sum()),
    "arbitration": int((cb["final_stage"] == "arbitration").sum()),
    "by_group": cb["reason_group"].value_counts().to_dict(),
}

res["portfolio"] = {
    "merchants": len(m), "transactions": int(con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]),
    "volume_cr": round(float(con.execute("SELECT SUM(amount) FROM transactions").fetchone()[0]) / 1e7, 1),
    "bad_merchants": int(m["is_bad"].sum()), "bad_by_typology": m.loc[m["is_bad"], "typology"].value_counts().to_dict(),
}
(OUT / "results.json").write_text(json.dumps(res, indent=2, default=str))

pd.set_option("display.width", 220, "display.max_columns", 20)
print(json.dumps(res["sanctions"], indent=1))
print(rat, "\n", by_typ, "\n")
print(scores.drop(columns=["target_typologies"]).to_string(index=False), "\n")
print(exp, "\n")
print(pq, "\n")
print({k: v for k, v in res["monitoring"].items() if k not in ("priority", "exposure")})
print(codes.to_string(index=False), "\n", stage.to_string(index=False))
print(json.dumps(res["chargebacks"], indent=1))
print(case.head(5)[["merchant_id", "priority", "rules", "recommended_action"]].to_string(index=False))
