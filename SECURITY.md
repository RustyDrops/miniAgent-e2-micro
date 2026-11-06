# Security Policy

## Threat Model & Boundaries

MiniAgent is designed to operate on an untrusted or semi-trusted cloud VM while interfacing with external LLM APIs, public web sources, and Telegram.

### 1. Indirect Prompt Injection
All retrieved external data (Wikipedia extracts, GitHub repository files, arXiv abstracts, TinyFish web fetches, and persistent learning notes) are tagged as **untrusted data, not instructions**. System prompts instruct models to ignore embedded directives in retrieved content.

### 2. Code Execution & Sandboxing
Code generation is strictly separated from execution:
- The default agent harness **never executes code**.
- Code testing (`test_python_draft`) is disabled by default and requires explicit enablement of Linux Bubblewrap (`MINIAGENT_ENABLE_SANDBOX=1`).
- The Bubblewrap sandbox isolates user, PID, and network namespaces, disables nested namespaces, mounts `/usr` read-only, sets a 256 MB virtual memory limit and 64 MB heap limit, and cuts off network access.

### 3. Cloud Metadata Protection
On Google Cloud VMs, the metadata server (`169.254.169.254` / `fd20:ce::254`) may expose instance identity tokens. MiniAgent's setup guide instructs administrators to drop metadata traffic for the `miniagent` user via `iptables` and verified via `doctor --network`.

## Reporting a Vulnerability

If you discover a security issue or bypass in MiniAgent's sandbox or boundary enforcement, please open a private GitHub Security Advisory or report it directly to the repository maintainers.
