"""Conservative, local customer matching for imported Helpdesk messages.

Customer contact values come only from the Redmine Zákazníci card. Neither
sender details nor message contents are logged or returned to the browser.
"""
import re
import unicodedata

from suggestions import emails, phones

SENDER_FIELDS = {
    "odesilatel", "email odesilatele", "e mail odesilatele",
    "adresa odesilatele", "kontakt odesilatele", "telefon odesilatele",
    "sender", "sender email", "from", "from email", "mail from",
}
SENDER_KEYS = ("sender_email", "sender_phone", "from_email", "mail_from")
SIGNOFF = re.compile(
    r"^(s pozdravem|s uctou|srdecne zdravim|zdravi|hezky den|"
    r"preji hezky den|preji krasny den|best regards|kind regards|regards)\b"
)
REPLY = re.compile(
    r"(?i)^(?:\s*>|[-_]{4,}|from:\s|od:\s|odesilatel:\s|"
    r"on .{3,120} wrote:|dne .{3,120} napsal(?:\(a\))?:)"
)


def _label(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def sender_metadata(issue):
    """Only explicitly named sender fields, never arbitrary issue contacts."""
    values = []
    for key in SENDER_KEYS:
        value = issue.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    for field in issue.get("custom_fields") or []:
        if not isinstance(field, dict) or _label(field.get("name", "")) not in SENDER_FIELDS:
            continue
        value = field.get("value")
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, list):
            values.extend(v for v in value if isinstance(v, str) and v.strip())
    return "\n".join(values)


def signature_block(description):
    """Extract first message's signature, never quotes or forwarded content."""
    lines = str(description or "").splitlines()
    first_message = []
    for line in lines:
        if REPLY.match(line.strip()):
            break
        first_message.append(line)
    for i, line in enumerate(first_message):
        if SIGNOFF.match(_label(line)):
            block = [line]
            for following in first_message[i + 1:i + 9]:
                if REPLY.match(following.strip()):
                    break
                block.append(following)
            return "\n".join(block)
    # Some signatures lack a formal sign-off; use only an explicitly
    # delimited signature, not the last arbitrary contact in the body.
    for i, line in enumerate(first_message):
        if line.strip() == "--":
            return "\n".join(first_message[i + 1:i + 9])
    return ""


def decide_customer(issue, catalog):
    """Return a decision with no email addresses or phone numbers in output.

    auto: one customer card has all recognized contact matches; review: a
    collision or unverified sender/signature disagreement; none: no match.
    """
    sender = sender_metadata(issue)
    signed = signature_block(issue.get("description"))
    source_values = (("sender", sender), ("signature", signed))
    matched = {}
    has_contacts = {}
    for source, value in source_values:
        source_emails, source_phones = emails(value), phones(value)
        has_contacts[source] = bool(source_emails or source_phones)
        matched[source] = {}
        for customer in catalog:
            contact = " ".join(v for v in customer.get("contacts", []) if isinstance(v, str))
            email_match = bool(source_emails & emails(contact))
            phone_match = bool(source_phones & phones(contact))
            if email_match or phone_match:
                matched[source][customer["id"]] = (
                    "e-mail a telefon" if email_match and phone_match
                    else "e-mail" if email_match else "telefon"
                )

    from_sender, from_signature = matched["sender"], matched["signature"]
    if len(from_sender) > 1 or len(from_signature) > 1:
        return {"status": "review", "reason": "Kontaktní údaj odpovídá více zákazníkům."}
    if from_sender and from_signature and set(from_sender) != set(from_signature):
        return {"status": "review", "reason": "Odesílatel a podpis ukazují na různé zákazníky."}
    if has_contacts["sender"] and not from_sender and from_signature:
        return {"status": "review", "reason": "Podpis odpovídá kartě, ale odesílatel nikoliv."}
    if len(from_sender) == 1:
        customer_id = next(iter(from_sender))
        return {
            "status": "auto", "customer_id": customer_id, "source": "sender",
            "reason": f"Přesná a jedinečná shoda {from_sender[customer_id]} v poli odesílatele."
        }
    if len(from_signature) == 1:
        customer_id = next(iter(from_signature))
        return {
            "status": "auto", "customer_id": customer_id, "source": "signature",
            "reason": f"Přesná a jedinečná shoda {from_signature[customer_id]} v podpisu první zprávy."
        }
    return {"status": "none", "reason": "Žádný jednoznačně rozpoznaný kontakt odesílatele."}
