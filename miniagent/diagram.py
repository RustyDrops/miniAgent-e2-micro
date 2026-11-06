"""Mermaid state and architecture diagram generator for MiniAgent."""


def generate_mermaid_diagram(queue, budget=None) -> str:
    """Generate an interactive Mermaid flowchart reflecting live queue and operational states."""
    counts = queue.counts() if queue else {}
    queued = counts.get('queued', 0)
    running = counts.get('running', 0)
    done = counts.get('done', 0)
    failed = counts.get('failed', 0)
    paused = 'PAUSED' if (queue and queue.paused()) else 'ACTIVE'

    spent_str = 'N/A'
    if budget:
        try:
            spent, limit = budget.today()
            spent_str = f'${spent / 1e6:.2f} / ${limit / 1e6:.2f}'
        except Exception:
            pass

    return f'''```mermaid
flowchart TD
    subgraph Trigger ["Triggers & Schedulers"]
        Telegram["Telegram User Chat"] --> Ingest["Queue Ingestion"]
        Cron["24h Objectives (Cron)"] --> Ingest
        FollowUp["Follow-Up Proposals"] --> Ingest
    end

    subgraph State ["Queue & Ledger (State: {paused})"]
        Ingest --> Q["Queued Jobs: {queued}"]
        Q --> Claim["Worker Claim"]
        Claim --> Running["Running Jobs: {running}"]
        BudgetGuard["Daily Ledger: {spent_str}"] -. Limits .-> Claim
    end

    subgraph Pipeline ["Sequential Specialist Engine"]
        Running --> Researcher["Researcher (Search & Verify)"]
        Researcher --> Builder["Builder (Draft & AST Check)"]
        Builder --> Reviewer["Reviewer (PR & User Report)"]
    end

    subgraph Outputs ["Safe Outcomes"]
        Reviewer --> Finished["Done: {done}"]
        Reviewer --> Failures["Failed: {failed}"]
        Reviewer --> DraftPR["GitHub Draft PR (Opt-in)"]
        Reviewer --> Clarify["User Clarification (/answer)"]
    end
```'''
