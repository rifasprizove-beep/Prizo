from decimal import Decimal, ROUND_HALF_UP

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    user, dom = email.split("@", 1)

    def _mask(s: str) -> str:
        if len(s) <= 2:
            return s[:1] + "*"
        return s[:2] + "***"

    dom_parts = dom.split(".")
    dom_parts[0] = _mask(dom_parts[0])
    return f"{_mask(user)}@{'.'.join(dom_parts)}"

def cents_to_usd(cents: int) -> float:
    return round(cents / 100.0, 2)

def round2(x: float | Decimal) -> float:
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
