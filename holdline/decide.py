def judge(findings: dict) -> str:
    policy = findings.get("policy") or {}
    shipment = findings.get("shipment") or {}
    verdicts = (policy.get("verdict"), shipment.get("verdict"))
    if any(item not in {"CLEAR", "BLOCK"} for item in verdicts):
        return "INCOMPLETE"
    if "BLOCK" in verdicts:
        return "BLOCKED"
    return "READY_FOR_REVIEW"
