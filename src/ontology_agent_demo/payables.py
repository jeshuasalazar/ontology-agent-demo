"""Invoice reconciliation (CFDI 4.0) as ontology rules: zero LLM tokens.

This replaces an LLM agent that read the payment manual on every run. The
manual now lives in ontology/accounts_payable.yaml, and every decision cites
the check that produced it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel

from .ontology import ROOT

AP_ONTOLOGY = ROOT / "ontology" / "accounts_payable.yaml"
INVOICES = ROOT / "data" / "payables" / "invoices"
NS = {"cfdi": "http://www.sat.gob.mx/cfd/4", "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital"}


class Invoice(BaseModel):
    file: str
    series: str
    folio: str
    issued: date
    uuid: str
    issuer_rfc: str
    receiver_rfc: str
    subtotal: Decimal
    transferred: Decimal
    withheld: Decimal
    total: Decimal
    payment_method: str


class Decision(BaseModel):
    invoice: Invoice
    supplier: str
    due: date | None
    status: str  # pay | clarify | reject | hold
    failed_checks: list[str]
    detail: str


class PaymentRun(BaseModel):
    run_date: date
    decisions: list[Decision]
    scheduled_total: Decimal
    budget: Decimal
    remaining: Decimal
    llm_tokens: int = 0


def parse_cfdi(path: Path) -> Invoice:
    root = ET.parse(path).getroot()
    imp = root.find("cfdi:Impuestos", NS)
    tfd = root.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    return Invoice(
        file=path.name,
        series=root.get("Serie", ""),
        folio=root.get("Folio", ""),
        issued=datetime.fromisoformat(root.get("Fecha")).date(),
        uuid=tfd.get("UUID").upper(),
        issuer_rfc=root.find("cfdi:Emisor", NS).get("Rfc"),
        receiver_rfc=root.find("cfdi:Receptor", NS).get("Rfc"),
        subtotal=Decimal(root.get("SubTotal")),
        transferred=Decimal(imp.get("TotalImpuestosTrasladados", "0")) if imp is not None else Decimal(0),
        withheld=Decimal(imp.get("TotalImpuestosRetenidos", "0")) if imp is not None else Decimal(0),
        total=Decimal(root.get("Total")),
        payment_method=root.get("MetodoPago", ""),
    )


def due_date(inv: Invoice, terms: dict) -> date:
    if "due_day_of_month" in terms:
        return inv.issued.replace(day=terms["due_day_of_month"])
    return inv.issued + timedelta(days=terms.get("credit_days", 0))


def reconcile(run_date: date, invoices_dir: Path = INVOICES, ontology_path: Path = AP_ONTOLOGY) -> PaymentRun:
    o = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    tol = Decimal(str(o["tolerance_mxn"]))
    rate = Decimal(str(o["iva_rate"]))
    seen: set[str] = set()
    decisions: list[Decision] = []
    for path in sorted(invoices_dir.glob("*.xml")):
        inv = parse_cfdi(path)
        sup = o["suppliers"].get(inv.issuer_rfc)
        failed, notes = [], []
        if inv.receiver_rfc != o["company_rfc"]:
            failed.append("receiver_rfc")
            notes.append(f"receiver RFC {inv.receiver_rfc}, expected {o['company_rfc']}")
        expected = inv.subtotal + inv.transferred - inv.withheld
        if abs(expected - inv.total) > tol:
            failed.append("totals_add_up")
            notes.append(f"{inv.subtotal} + {inv.transferred} - {inv.withheld} = {expected}, invoice says {inv.total} (diff {inv.total - expected})")
        if (inv.subtotal * rate).quantize(Decimal("0.01")) != inv.transferred:
            failed.append("iva_is_16_percent")
            notes.append(f"IVA {inv.transferred} is not 16% of {inv.subtotal}")
        if inv.uuid in seen:
            failed.append("unique_uuid")
            notes.append(f"duplicate fiscal folio {inv.uuid}")
        seen.add(inv.uuid)
        if sup is None:
            failed.append("known_supplier")
            notes.append(f"supplier {inv.issuer_rfc} is not approved")
        if {"unique_uuid", "known_supplier"} & set(failed):
            status = "reject"
        elif failed:
            status = "clarify"
        else:
            status = "pay"
            if inv.payment_method == "PPD":
                notes.append("PPD: request the payment complement after paying")
        decisions.append(Decision(invoice=inv, supplier=sup["name"] if sup else inv.issuer_rfc,
                                  due=due_date(inv, sup["terms"]) if sup else None,
                                  status=status, failed_checks=failed, detail="; ".join(notes) or "all checks pass"))

    budget = Decimal(str(o["weekly_budget_mxn"]))
    remaining = budget
    for d in sorted((d for d in decisions if d.status == "pay"), key=lambda d: (d.due, d.invoice.file)):
        if d.invoice.total <= remaining:
            remaining -= d.invoice.total
        else:
            d.status, d.detail = "hold", f"over budget: {remaining} left"
    scheduled = budget - remaining
    return PaymentRun(run_date=run_date, decisions=decisions, scheduled_total=scheduled, budget=budget, remaining=remaining)
