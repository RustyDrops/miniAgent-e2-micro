# AnnIs-Mini comparison

Reviewed [AnnIs-Mini](https://github.com/RustyDrops/AnnIs-Mini) as a reference for MiniAgent's resource-constrained agent design.

- **Planning and handoffs:** [AnnIs's agent core](https://github.com/RustyDrops/AnnIs-Mini/blob/main/agent_core.py) has a planner and specialist handoffs. MiniAgent passes bounded notes between roles and now includes an optional, validated planner that can omit roles while retaining review. The fixed researcher → builder → reviewer sequence remains the default. Measure quality and total cost with real models before enabling the experimental planner by default.
- **Memory:** [AnnIs's memory module](https://github.com/RustyDrops/AnnIs-Mini/blob/main/memory.py) uses indexed organization. MiniAgent currently searches a capped collection of unverified notes by scanning files. Indexing may matter if the cap grows, but is not needed to justify extra machinery at the current scale.
- **Context:** AnnIs includes [conversation summarization](https://github.com/RustyDrops/AnnIs-Mini/blob/main/agent_summary.py). MiniAgent creates a new bounded context per task, so persistent conversation summarization is a future need only if multi-turn task memory is introduced.
- **Already covered:** Both designs use specialized tools, budgeting, and background work. MiniAgent adds a persistent queue, pre-request cost reservations, scoped specialist tools, and reviewable GitHub draft changes. Keep these properties when experimenting with planning.

This is a design comparison, not a claim that either implementation has been validated on the target VM. Do not automatically import third-party code, prompts, or credentials.
