"""Narrated terminal demo: a bank and its lending market in one Samyama graph.

Record with asciinema, then render the GIF with agg:
    asciinema rec --headless --window-size 110x34 -i 5 -c "python -m demo.demo" demo/banking-kg.cast
    agg --font-size 15 demo/banking-kg.cast demo/banking-kg.gif

Runs against a loaded engine (BANKING_KG_URL, BANKING_KG_GRAPH; defaults in etl/config.py) and walks
through the high-level questions a bank's risk, finance, compliance and marketing teams ask. The market
answers are real public data (HMDA, GLEIF, FDIC Call Reports, SBA, Washington DC 2023); the bank answers
come from Banking-KG Bank, a fictional bank with synthetic customers.
"""

from __future__ import annotations

import os
import time

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from etl import config
from etl.helpers import Engine

console = Console()
PAUSE_S = float(os.environ.get("DEMO_PAUSE", "4"))  # seconds to hold each answer on screen


def pause(scale: float = 1.0) -> None:
    """Hold the screen so a viewer can read it."""
    time.sleep(PAUSE_S * scale)


def step(title: str) -> None:
    """A titled section."""
    console.print()
    console.rule(f"[bold cyan]{title}")
    pause(0.4)


def ask(db: Engine, cypher: str, columns: list[str], label: str, money: tuple[int, ...] = ()) -> list:
    """Show the Cypher, run it, print the rows as a small table."""
    console.print(f"  [dim]cypher>[/dim] [yellow]{escape(cypher)}[/yellow]")
    rows = db.q(cypher)
    console.print(f"  [green]→[/green] [bold]{escape(label)}[/bold]")
    table = Table(show_edge=False, pad_edge=False, box=None, padding=(0, 2))
    for c in columns:
        table.add_column(c, justify="right" if c[:1] in "#$" or c.startswith(("avg", "rate", "kept", "growth")) else "left")
    for r in rows:
        table.add_row(
            *[
                ("yes" if v else "no")
                if isinstance(v, bool)
                else f"${v:,.0f}"
                if i in money and isinstance(v, (int, float))
                else f"{v:,.2f}"
                if isinstance(v, float)
                else f"{v:,}"
                if isinstance(v, int)
                else str(v)
                for i, v in enumerate(r)
            ]
        )
    console.print(table, style="", justify="left")
    pause()
    return rows


def main() -> None:
    """Six questions, market first, then the bank, then the two together."""
    db = Engine(config.ENGINE_URL, config.GRAPH)
    console.print(
        Panel.fit(
            "[bold]Samyama · banking-kg — a bank and its market in one graph[/bold]\n"
            '"Where did this number come from, who are we competing with, and which customers are leaving?"\n'
            "[dim]market: HMDA · GLEIF · FDIC Call Reports · SBA (Washington DC 2023, public)   "
            "bank: Banking-KG Bank (synthetic)[/dim]",
            border_style="cyan",
        )
    )
    pause(1.0)

    step("1 · What is in the graph — and what is real?")
    ask(
        db,
        "MATCH (n) RETURN coalesce(n.synthetic, false) AS synthetic, count(n) AS nodes",
        ["synthetic", "# nodes"],
        "every bank-layer node is marked synthetic; the market is public data",
    )

    step("2 · Reconciliation: who keeps what they write?")
    console.print(
        "  [dim]HMDA originations kept on balance sheet vs. the change in Call Report residential loans "
        "— two regulators, joined by LEI → GLEIF → FDIC certificate[/dim]"
    )
    pause(0.6)
    ask(
        db,
        "MATCH (l:Lender)<-[:ORIGINATED_BY]-(n:Loan) WHERE NOT (n)-[:SOLD_TO]->() "
        "WITH l, count(n) AS kept MATCH (l)-[:FILED]->(a:Filing {period: '2022Q4'}), (l)-[:FILED]->(b:Filing {period: '2023Q4'}) "
        "RETURN l.name AS lender, kept, b.residential_re_loans_k - a.residential_re_loans_k AS growth_k ORDER BY kept DESC LIMIT 4",
        ["lender", "kept loans", "growth ($K)"],
        "DC loans kept vs. reported residential-loan growth ($ thousands)",
    )

    step("3 · Concentration: who dominates the core mortgage product?")
    ask(
        db,
        "MATCH (l:Lender)<-[:ORIGINATED_BY]-(n:Loan)<-[:ORIGINATED_AS]-(:Application)-[:FOR_PRODUCT]->"
        "(:LoanProduct {name: 'Conventional:First Lien'}) RETURN l.name AS lender, count(n) AS loans, "
        "avg(n.interest_rate) AS avg_rate ORDER BY loans DESC LIMIT 5",
        ["lender", "# loans", "avg rate %"],
        "top originators of conventional first-lien mortgages, DC 2023",
    )

    step("4 · Fair lending: what would an examiner see first?")
    ask(
        db,
        "MATCH (t:Tract)<-[:IN_TRACT]-(a:Application)-[:DENIED_FOR]->(r:DenialReason) WHERE t.income_pct_of_msa < 50 "
        "RETURN r.name AS reason, count(DISTINCT a) AS denials ORDER BY denials DESC LIMIT 4",
        ["denial reason", "# denials"],
        "denials in low-income tracts (< 50% of area median income)",
    )

    step("5 · Credit risk: where do guaranteed small-business loans fail?")
    ask(
        db,
        "MATCH (i:Industry)<-[:IN_INDUSTRY]-(:Business)-[:BORROWED]->(s:SBALoan {status: 'Charged off'}) "
        "RETURN i.name AS industry, count(s) AS charged_off, sum(s.charge_off_amount) AS lost "
        "ORDER BY lost DESC LIMIT 4",
        ["industry", "# charged off", "$ lost"],
        "SBA charge-offs by industry",
        money=(2,),
    )

    step("6 · Our bank: which customers are moving money to competitors?")
    ask(
        db,
        "MATCH (c:Customer)-[:OWNS]->(:Account)-[s:SENDS_TO]->(k:Counterparty) WHERE c.status = 'ACTIVE' AND s.count >= 2 "
        "RETURN k.name AS competitor, count(DISTINCT c) AS customers, sum(s.total) AS sent ORDER BY sent DESC LIMIT 4",
        ["competitor (fictional)", "# customers", "$ sent"],
        "retention risk — a campaign list, not a guess",
        money=(2,),
    )

    step("7 · Across the line: our mortgages vs. the market's")
    console.print("  [dim]the bank's own loans are classified in HMDA's product taxonomy, so they sit beside every DC origination[/dim]")
    pause(0.6)
    ask(
        db,
        "MATCH (c:CustomerLoan)-[:CLASSIFIED_AS]->(p:LoanProduct {name: 'Conventional:First Lien'}) "
        "WHERE c.origination_date STARTS WITH '2023' RETURN 'Banking-KG Bank' AS book, count(c) AS loans, "
        "avg(c.current_interest_rate) AS avg_rate "
        "UNION ALL MATCH (a:Application)-[:ORIGINATED_AS]->(n:Loan) MATCH (a)-[:FOR_PRODUCT]->(:LoanProduct {name: 'Conventional:First Lien'}) "
        "RETURN 'DC market' AS book, count(n) AS loans, avg(n.interest_rate) AS avg_rate",
        ["book", "# loans", "avg rate %"],
        "2023 conventional first-lien mortgages",
    )

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Two regulators' filings and one bank's customers, answered on one engine[/bold green]\n"
            "75,179 nodes · 241,222 relationships · Cypher, vector search, NLQ and graph algorithms",
            border_style="green",
        )
    )
    pause(1.5)


if __name__ == "__main__":
    main()
