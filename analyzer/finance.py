"""Deterministic simple-equity/post-money SAFE scenario arithmetic.

Fees are an upfront fraction of total outlay. Carry applies to positive profit
above that outlay. No interim flows, preference stack or debt waterfall is assumed.
"""
import math

from .models import Economics


def calculate(economics: Economics | dict) -> dict:
    e = economics if isinstance(economics, Economics) else Economics.model_validate(economics)
    blockers = list(e.limitations)
    if not e.supported or e.instrument == "unsupported":
        blockers.append("Security structure is unsupported or not established.")
    required = ["entry_post_money", "retained_fraction", "fee_fraction", "carry_fraction", "holding_years"]
    for name in required:
        value = getattr(e, name)
        if value is None or not math.isfinite(value):
            blockers.append(f"Missing or invalid {name}.")
    if blockers:
        return {"supported": False, "blockers": blockers}
    if e.entry_post_money <= 0 or not 0 < e.retained_fraction <= 1 or not 0 <= e.fee_fraction < 1 or not 0 <= e.carry_fraction < 1 or e.holding_years <= 0:
        return {"supported": False, "blockers": ["Invalid valuation, dilution, fee, carry or holding-period input."]}
    if e.investment is not None and (not math.isfinite(e.investment) or e.investment <= 0 or e.investment * (1 - e.fee_fraction) > e.entry_post_money):
        return {"supported": False, "blockers": ["Investment must be positive and cannot buy more than 100% ownership."]}
    exposure = (1 - e.fee_fraction) * e.retained_fraction
    # net = gross - carry * max(gross - 1, 0)
    gross_for_100 = (100 - e.carry_fraction) / (1 - e.carry_fraction)
    target = e.entry_post_money * gross_for_100 / exposure
    cases = {}
    for label in ("downside", "base", "upside"):
        value = getattr(e, f"exit_{label}")
        if value is None:
            continue
        if not math.isfinite(value) or value < 0:
            return {"supported": False, "blockers": [f"Invalid {label} exit equity value."]}
        gross = value / e.entry_post_money * exposure
        net = gross - e.carry_fraction * max(gross - 1, 0)
        cases[label] = {"exit_equity_value": value, "net_moic": net,
                        "annualized_return": net ** (1 / e.holding_years) - 1,
                        "net_proceeds": net * e.investment if e.investment else None}
    ordered = [cases[k]["exit_equity_value"] for k in ("downside", "base", "upside") if k in cases]
    if ordered != sorted(ordered):
        return {"supported": False, "blockers": ["Scenario values must increase from downside to upside."]}
    return {"supported": True, "currency": e.currency, "required_exit_for_100x": target,
            "holding_years": e.holding_years, "scenarios": cases,
            "initial_ownership": e.investment * (1 - e.fee_fraction) / e.entry_post_money if e.investment else None,
            "formula": "gross multiple = exit equity / entry post-money × retained fraction × (1 − upfront fee); net = gross − carry × max(gross − 1, 0)",
            "assumptions": e.assumptions,
            "scope": "Single initial outlay and single exit; annualized return is not multi-cash-flow IRR. SAFE assumes its post-money cap determines conversion ownership; no preference advantage is modeled. Downside scenario is not a maximum loss."}


def verdict(hundred: dict, defensive: dict, calculation: dict, gaps: list[str], confidence: str) -> tuple[str, str, list[str]]:
    blockers = list(gaps)
    if not calculation.get("supported"):
        blockers += calculation.get("blockers", ["Return economics are unverified."])
    if confidence == "low":
        blockers.append("Evidence confidence is low.")
    if blockers:
        return "PASS", "Neither established", list(dict.fromkeys(blockers))
    cases = calculation.get("scenarios", {})
    qualifies_a = (hundred.get("qualifies") and not hundred.get("blockers") and bool(hundred.get("source_ids"))
                   and cases.get("upside", {}).get("net_moic", -1) >= 100 - 1e-9)
    # Minimum consistency gate, not a guarantee or personalized risk threshold.
    qualifies_b = (defensive.get("qualifies") and not defensive.get("blockers") and bool(defensive.get("source_ids"))
                   and cases.get("downside", {}).get("net_moic", -1) >= 1
                   and cases.get("base", {}).get("net_moic", -1) > 1)
    if qualifies_a or qualifies_b:
        basis = "100× potential + downside protection" if qualifies_a and qualifies_b else "100× potential" if qualifies_a else "Downside protection"
        return "INVEST", basis, []
    failures = hundred.get("blockers", []) + defensive.get("blockers", [])
    if not failures:
        failures = ["Neither a credible 100× return nor sufficient downside protection is established at these terms."]
    return "PASS", "Neither established", failures
