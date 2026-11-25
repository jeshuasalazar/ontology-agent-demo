"""The rules reproduce the decisions of the LLM invoice agent, with zero tokens."""

from datetime import date
from decimal import Decimal

from ontology_agent_demo.payables import reconcile


def test_same_decisions_as_the_llm_agent():
    run = reconcile(date(2026, 10, 13))
    status = {d.invoice.file[:2]: d.status for d in run.decisions}
    assert status == {"01": "pay", "02": "pay", "03": "pay", "04": "clarify", "05": "clarify", "06": "reject"}
    assert run.scheduled_total == Decimal("32190.00") and run.remaining == Decimal("7810.00")
    assert run.llm_tokens == 0


def test_each_decision_cites_the_failed_check():
    by = {d.invoice.file[:2]: d for d in reconcile(date(2026, 10, 13)).decisions}
    assert by["04"].failed_checks == ["totals_add_up"] and "diff 127.00" in by["04"].detail
    assert by["05"].failed_checks == ["receiver_rfc"]
    assert by["06"].failed_checks == ["unique_uuid"]


# Edge cases a real accounts-payable run meets. Each builds a CFDI 4.0 in a temp folder.
CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  Version="4.0" Serie="T" Folio="1" Fecha="{issued}T10:00:00" SubTotal="{subtotal}" {discount} Moneda="{currency}"
  Total="{total}" TipoDeComprobante="{kind}" MetodoPago="PUE">
  <cfdi:Emisor Rfc="{issuer}"/><cfdi:Receptor Rfc="CCO140215AB3"/>
  <cfdi:Conceptos>{lines}</cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="{iva}"/>
  <cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{uuid}"/></cfdi:Complemento>
</cfdi:Comprobante>"""
LINE = """<cfdi:Concepto Importe="{base}"><cfdi:Impuestos><cfdi:Traslados>
  <cfdi:Traslado Base="{base}" Impuesto="002" TipoFactor="{factor}" TasaOCuota="{rate}" Importe="{iva}"/>
</cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto>"""


def _run(
    tmp_path,
    issuer="NNS180509K21",
    issued="2026-10-01",
    currency="MXN",
    kind="I",
    discount=None,
    lines=(("100.00", "Tasa", "0.160000", "16.00"),),
    total=None,
):
    rendered = "".join(LINE.format(base=b, factor=f, rate=r, iva=i) for b, f, r, i in lines)
    iva = sum(Decimal(i) for *_, i in lines)
    subtotal = sum(Decimal(b) for b, *_ in lines) + Decimal(discount or 0)
    total = total or subtotal - Decimal(discount or 0) + iva
    (tmp_path / "t.xml").write_text(
        CFDI.format(
            issued=issued,
            subtotal=subtotal,
            discount=f'Descuento="{discount}"' if discount else "",
            currency=currency,
            total=total,
            kind=kind,
            issuer=issuer,
            lines=rendered,
            iva=iva,
            uuid="11111111-2222-3333-4444-555555555555",
        )
    )
    return reconcile(date(2026, 10, 13), invoices_dir=tmp_path).decisions[0]


def test_discount_is_part_of_the_total(tmp_path):
    d = _run(tmp_path, discount="50.00")
    assert d.status == "pay", d.detail


def test_iva_is_rounded_per_concept_like_the_sat(tmp_path):
    # 3 lines of 33.33: per-line IVA 5.33 each = 15.99; 16% of the summed base is 15.9984 → 16.00
    d = _run(tmp_path, lines=[("33.33", "Tasa", "0.160000", "5.33")] * 3)
    assert d.status == "pay", d.detail


def test_zero_rate_and_exempt_lines_are_valid(tmp_path):
    d = _run(
        tmp_path,
        lines=[
            ("100.00", "Tasa", "0.160000", "16.00"),
            ("80.00", "Tasa", "0.000000", "0.00"),
            ("40.00", "Exento", "", "0"),
        ],
    )
    assert d.status == "pay", d.detail


def test_wrong_iva_on_one_line_is_flagged(tmp_path):
    d = _run(tmp_path, lines=[("100.00", "Tasa", "0.160000", "16.00"), ("200.00", "Tasa", "0.160000", "30.00")])
    assert d.status == "clarify" and d.failed_checks == ["iva_is_16_percent"] and "line 2" in d.detail


def test_a_credit_note_is_never_paid(tmp_path):
    d = _run(tmp_path, kind="E")
    assert d.status == "clarify" and d.failed_checks == ["income_invoice"]


def test_foreign_currency_waits_for_a_person(tmp_path):
    d = _run(tmp_path, currency="USD")
    assert d.status == "clarify" and d.failed_checks == ["currency"]


def test_due_day_of_month_rolls_to_next_month(tmp_path):
    # Rent is due on day 1: an invoice issued on Oct 15 is due Nov 1, not Oct 1 (already past).
    assert _run(tmp_path, issuer="TCI110120HG5", issued="2026-10-15").due == date(2026, 11, 1)


def test_due_day_is_clamped_to_month_end():
    from ontology_agent_demo.payables import Invoice, due_date

    inv = Invoice(
        file="x",
        series="",
        folio="",
        issued=date(2026, 2, 10),
        uuid="u",
        issuer_rfc="r",
        receiver_rfc="r",
        subtotal=0,
        transferred=0,
        withheld=0,
        total=0,
        payment_method="PUE",
    )
    assert due_date(inv, {"due_day_of_month": 31}) == date(2026, 2, 28)
