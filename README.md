# MiniAgent — Autonomous Agent for GCP e2-micro

[![CI](https://github.com/RustyDrops/miniAgent-e2-micro/actions/workflows/test.yml/badge.svg)](https://github.com/RustyDrops/miniAgent-e2-micro/actions/workflows/test.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Budget](https://img.shields.io/badge/daily_budget-%240.50--%241.00-green)
![Platform](https://img.shields.io/badge/GCP-e2--micro%20Free%20Tier-orange)
![Tests](https://img.shields.io/badge/tests-94%20passed-brightgreen)

MiniAgent is a small, highly resource-constrained Python autonomous agent harness designed specifically for Google Cloud's Free Tier **`e2-micro` Linux VM** (1 GB RAM, shared 0.25 vCPU, 30 GB standard disk). It executes sequential specialist roles (Researcher $\rightarrow$ Builder $\rightarrow$ Reviewer), strictly bounds spending to **\$0.50–\$1.00/day**, runs 16+ deterministic zero-cost tools, logs complete execution telemetry, and interacts over a private Telegram chat with opt-in GitHub draft pull requests. Zero third-party Python dependencies—pure standard library & SQLite.

**This is a starting point, not a finished autonomous coding system.** It can research on a schedule, remember sourced notes, draft a static blog, and open a reviewed draft as a GitHub draft pull request. An optional experimental Linux sandbox can run a small Python draft with a test script once configured. The agent does not yet invent its own objectives or deploy a website automatically. Research can search GitHub, Wikipedia, and arXiv; it can read paged excerpts of public repository files, Wikipedia articles, and arXiv abstracts. It cannot browse arbitrary websites or independently guarantee source accuracy. The roles are model calls, not independent processes. Read [VM setup](docs/VM_SETUP.md) for beginner-friendly installation, Telegram and security instructions.

## Models and costs

The example below uses Meta Muse Spark 1.3 Contributor for the first two roles and OpenAI GPT-6 Luna Flex for review. Both need their own API credentials and provider access; a ChatGPT subscription is not itself an API key. Meta Contributor permits Meta to use submitted content, including prompts, files, code, and outputs, to train future models: use only content you are comfortable sharing. See [Meta pricing and Contributor terms](https://dev.meta.ai/docs/pricing-rate-limits), [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna), and [Flex processing](https://developers.openai.com/api/docs/guides/flex-processing). Flex can be slower or temporarily unavailable; there is no automatic upgrade to a more expensive tier.

For a Flex HTTP 429, MiniAgent retries the individual model request once by default, after a short delay; it does not rerun earlier tool actions. It retains the first reservation and reserves again before retrying, so its ledger can conservatively overestimate costs. It will not retry earlier than a provider-specified delay over 30 seconds, and it does not automatically retry timeouts or uncertain network failures. Configure `MINIAGENT_MAX_RETRIES` from 0 to 2 and `MINIAGENT_RETRY_WAIT_SECONDS` from 1 to 30. The reviewer Flex timeout defaults to 900 seconds; set `MINIAGENT_SECONDARY_TIMEOUT_SECONDS` between 5 and 900 to change it. Telegram polling continues while a model request waits, but the serial worker cannot begin another task until the current one finishes.

Configure the protected `/etc/miniagent.env` file in the setup guide, with your own keys and IDs. These example prices were checked on November 5, 2026 and must be checked against your own providers before use. Prices are USD per million tokens. No secrets belong in this repository or zip.

```ini
MINIAGENT_API_KEY=YOUR_META_API_KEY
MINIAGENT_BASE_URL=https://api.meta.ai/v1
MINIAGENT_MODEL=muse-spark-1.3-contributor
MINIAGENT_INPUT_USD_PER_MILLION=0.10
MINIAGENT_OUTPUT_USD_PER_MILLION=0.20
MINIAGENT_SECONDARY_API_KEY=YOUR_OPENAI_API_KEY
MINIAGENT_SECONDARY_BASE_URL=https://api.openai.com/v1
MINIAGENT_SECONDARY_MODEL=gpt-6-luna
MINIAGENT_SECONDARY_INPUT_USD_PER_MILLION=0.125
MINIAGENT_SECONDARY_OUTPUT_USD_PER_MILLION=0.50
MINIAGENT_SECONDARY_SERVICE_TIER=flex
MINIAGENT_DAILY_USD=0.50
MINIAGENT_DB=/var/lib/miniagent/state.db
MINIAGENT_STATE_DIR=/var/lib/miniagent
MINIAGENT_WORKSPACE=/var/lib/miniagent/workspace
TINYFISH_API_KEY=YOUR_OPTIONAL_TINYFISH_API_KEY
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_USER_ID=YOUR_NUMERIC_USER_ID
TELEGRAM_CHAT_ID=YOUR_NUMERIC_PRIVATE_CHAT_ID
```

Omit all `MINIAGENT_SECONDARY_*` entries to use the primary model for review too. Luna Flex's listed rates are $0.05 input and $0.25 output per million; the example deliberately budgets at the higher standard cache-write and output rates to allow for a tier mismatch. The ledger reserves estimated worst-case token cost before each request, reconciles reported usage when available, and retains reservations on uncertain failures. It uses UTC days and applies the configured conservative rates even to cached input. This is a **best-effort model API guard, not a guaranteed $1 total bill cap**: changes in pricing, token accounting, provider-side fees, retries outside this service, exchange rates, taxes, and cloud costs are outside its control. Configure provider spending limits and Google Cloud billing alerts and inspect actual invoices. The example $0.50 model limit leaves room for other costs but does not guarantee the rest costs under $0.50.

In Telegram, `/budget` breaks today's ledger down by requested model and tier, with reported input, output and cached input tokens where available. It also shows unsettled reservations. The displayed dollar amounts use the configured conservative prices, not the provider's invoice; cache counts are observational and do not reduce the ledger charge. Requests without complete usage data remain reserved and contribute no token counts. Old ledger entries remain counted but are labeled `unknown` because they predate model attribution. No prompt or response text is stored in these usage records.

## Local operation and verification

Use Python 3.10 or newer. With the environment configured, run `python3 -m miniagent task "Describe a small useful tool"` or `python3 -m miniagent telegram`. `python3 -m miniagent doctor` checks local configuration without network requests; adding `--live` makes up to two paid model requests charged against the configured budget ledger, and `--network` checks public endpoints, Telegram token acceptance and metadata-port exposure. See the VM setup guide for running it safely under the service account. Only one Telegram process should use a bot token and database at a time. Telegram messages must come from both configured IDs and a private chat. Tasks are durably queued and run serially. If the process restarts during a task, it reports the task as interrupted rather than automatically repeating work or billing; resubmit it if appropriate. Telegram result delivery may be repeated after a network interruption. Commands are acknowledged separately from execution, so resend a command if the service restarts before confirming it. Run offline checks with `python3 -m unittest discover -s tests`.

The offline suite includes a simulated provider workflow through the real queue, model adapters, budget ledger, draft tools, learning notes, and follow-up staging, including a simulated provider failure. The network responses are fakes; these checks do not validate live provider compatibility or prove resistance to prompt injection.

Each specialist receives a smaller set of built-in tool definitions matched to its role. The researcher can search and save learning notes, the builder can create and test drafts, and the reviewer can inspect work and propose bounded follow-ups. The harness rejects built-in tool calls outside the specialist's advertised set; this reduces prompt size and accidental cross-role actions, but does not make model output or retrieved material trustworthy. An empty specialist response stops the task instead of being treated as a successful completion.

An experimental model-selected planner can be enabled by setting `MINIAGENT_PLANNER=1` in the service environment. It makes one additional primary-model call, capped at 128 output tokens and charged to the same ledger, then chooses among four fixed sequences; every sequence ends with the reviewer. An invalid plan falls back to the full sequence, while a provider or budget error stops the task. The chosen sequence appears in the result. This is disabled by default because it can misclassify a task and omit a needed specialist; compare real task quality and total costs before relying on it. Set `MINIAGENT_PLANNER=0` or omit it to use the fixed sequence.

`python3 -m miniagent eval-planner --live` runs eight synthetic routing examples through the primary model, without executing the examples or tools. It reports the expected and selected sequences, missing or extra roles, fallbacks, elapsed time, and the ledger change. It can make up to eight paid requests, even when the planner is disabled for normal tasks; every request uses the normal budget guard. A failure stops the run and returns partial results. The examples are a small routing smoke test, not an evaluation of actual task output quality, prompt-injection resistance, or overall cost savings. Ledger change can include other concurrent activity or be affected by a UTC day rollover. See the VM setup guide for the service-account command.

Use `/status` to see queued work and the model ledger, `/pause` to stop starting jobs (a running job continues), and `/resume` to resume. The first Telegram startup adds one daily research-and-learning objective; the first run is 24 hours later. Use `/objectives` to see it and `/unschedule ID` to remove it permanently. `/schedule 24 Research one promising small-agent optimization and draft a report` adds another 24-hour objective. There are at most five objectives, the shortest interval is six hours, and missed runs are not replayed as a burst. New recurring jobs and queued background jobs wait when the model ledger has reached 75% of its daily allowance, leaving room for user-directed tasks. A job already running can still spend against the remaining ledger allowance. This is not a separate daily allocation or a cap on non-model charges. `/pause` persists across restarts. The queue holds up to 20 pending, proposed or running tasks; user-submitted tasks take priority. When upgrading an older database, previously queued jobs have no origin information and are treated as user tasks.

Use `/jobs` to list active work and the five most recent finished tasks, `/job ID` to read a task and its saved result, and `/cancel ID` to cancel a queued or proposed task. Use `/history` (or `python3 -m miniagent history`) to inspect recent task run durations, states, and error types; `/history ID` shows detailed telemetry for a specific run. Use `/postmortem` (or `python3 -m miniagent postmortem`) to generate a diagnostic report that analyzes failure patterns, error classifications, and operational recommendations. If an ambiguous task requires clarification, the agent can use `propose_question`; pending questions are notified in chat and listed with `/questions`. Send `/answer ID YOUR_ANSWER` to provide input and continue the task as a prioritized new job. Cancellation cannot stop an already running request. Cancelling one occurrence of a recurring objective does not disable later occurrences; use `/unschedule ID` with the objective ID to do that. Results, questions, and task text are stored in the private SQLite database (operating in WAL mode for low IOPS overhead), so protect backups accordingly.

`/health` returns a read-only snapshot of VM memory, workspace filesystem space, load averages, process memory, and—when available—cgroup service memory and CPU quota. The specialists can access the same measurements when assessing optimizations. `null` means a value is unavailable or has no numeric limit. Load averages are not CPU percentages, and the cgroup CPU quota does not necessarily represent the e2-micro's shared-CPU baseline. These are point-in-time observations, not monitoring or a guarantee against resource exhaustion.

During a recurring research task, the agent may propose one focused follow-up. At most two follow-ups may be proposed per UTC day; they are queued only if the parent finishes successfully and cannot create further follow-ups. Failed or interrupted parents cancel their staged proposals. Follow-ups share the background budget threshold and cannot bypass publication or execution restrictions. Results are sent to the configured Telegram chat like other tasks. This adds a bounded feedback loop, not unrestricted autonomous self-modification.

The draft workspace is separate from the application and service files. Models do not receive the API, bot or GitHub keys as prompt variables, but never place secrets in tasks, drafts, or source material. The service sandbox is hardening rather than safe isolation for arbitrary code. Review generated content before executing it or making it public.

Draft tools create files without overwriting existing files. The agent can read a file in bounded pages and append or replace one exact passage using its latest SHA-256 hash. If the file has changed, or a replacement is ambiguous, the edit is rejected. The check assumes one editor at a time; it is not a cross-process locking protocol. Each draft is limited to 20 KB. Three tool rounds per specialist are allowed by default; `MINIAGENT_MAX_TOOL_ROUNDS` can be set from 0 to 5, with more rounds potentially increasing cost.

Research tools use unauthenticated requests to fixed GitHub, Wikipedia and arXiv endpoints; public API rate limits and connectivity failures apply. When `TINYFISH_API_KEY` is configured, the agent also gains access to free-tier `web_search` (TinySearch) and `web_fetch` (TinyFetch) to browse and ingest clean markdown from live technical documentation and websites with zero token waste on HTML/CSS boilerplate. GitHub file results include an immutable Git blob API URL and an ordinary current-file viewing URL. arXiv results provide paper metadata and abstracts, not the full paper, and may be unreviewed preprints. Source text is untrusted, returned in short excerpts, and may omit context. Check citations and facts yourself before relying on or publishing a report. Live connectivity on the VM remains to be checked.

The agent can save, find and recall short notes with source URLs in its workspace. Notes are marked unverified and treated as data, never as system instructions or installed code. This is persistent reference memory, not model retraining or proof that a new skill works. The agent can draft a potential improvement; an optional sandbox can test two-file Python drafts but cannot install them. The design draws on [Picoling's](https://github.com/RustyDrops/Picoling) persistent skills, background work and budget-aware operation while retaining the VM-specific protections described here.

## Experimental Python draft tests

The `test_python_draft` tool is **disabled by default** and never falls back to running code outside its sandbox. The agent can write a Python file and a separate test file that imports it as `subject`; it can ask the tool to run those two files. It receives the exit status and up to 1,200 bytes of output. A passing test is untrusted evidence, not proof of safety or correctness.

On a dedicated Linux VM, install the distribution's `bubblewrap` package, then run the controlled check as the service account:

```sh
sudo apt-get install -y bubblewrap
cd /opt/miniagent
sudo -u miniagent env MINIAGENT_ENABLE_SANDBOX=1 /usr/bin/python3 deploy/check_sandbox.py
```

The check exercises importing a copied draft, absence of a canary environment variable and the service env file, inability to reach the IPv4 and IPv6 cloud metadata addresses, and failure to create a nested user namespace. If it fails, leave the feature disabled. If it passes, add `MINIAGENT_ENABLE_SANDBOX=1` to the protected `/etc/miniagent.env` and restart the service, then verify a controlled test through the running service: systemd restrictions can differ from the manual check. The runner requires unprivileged Linux namespaces and Bubblewrap options including `--size` and `--disable-userns`; some kernels, distributions, or service settings will reject them. Such failures are reported, never retried without isolation.

Bubblewrap gives the test its own user, PID and network namespaces, disables further user-namespace creation, clears the environment, mounts `/usr` read-only, exposes only copies of the two draft files, and applies a bounded temporary filesystem plus CPU, memory, process, file-size and wall-time limits. It shares the host kernel and does not use a seccomp filter; it is **not a hardened boundary against hostile code or kernel vulnerabilities**. Keep the VM patched, avoid sensitive data on it, and use a separate stronger isolation environment for untrusted code if those risks are unacceptable. The check does not prove the sandbox is secure. This runner and its systemd interaction have not yet been tested on the target VM.

## Optional GitHub draft pull requests

Create a dedicated GitHub repository, initialize it with a README, and give a fine-grained token access only to that repository, with Contents and Pull requests read/write permissions. Follow [GitHub's token guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens). In the protected `/etc/miniagent.env`, add `MINIAGENT_GITHUB_REPO=RustyDrops/miniAgent-e2-micro` and `MINIAGENT_GITHUB_TOKEN=your_token`, then restart the service. Do not put the token into Telegram. GitHub organization rules may additionally restrict pull request creation or require token approval.

Ask the agent to create a draft, then send `/preview report.md` (replace the path with its actual workspace path; paths with spaces are not supported). Telegram shows the complete file and SHA-256 digest. Review the text carefully, including secrets and sensitive content, and use the displayed `/publish PATH SHA256` command to open a **draft** pull request. The hash binds the request to those exact bytes. This command creates a unique branch and adds one file under `contributions/`; it never pushes to the default branch, merges, executes the draft, or deploys it. A failed request may leave a branch or even a pull request behind, so check GitHub for the named branch before trying again. Results, including a PR on a public repository, may be public. Disable or carefully restrict Actions and other automation in this repository: opening a PR can trigger repository-configured automation. GitHub connectivity and token permissions have not been verified live.

For a small multi-file project, ask the agent to put related files under one workspace directory, such as `projects/example/`. Send `/preview_bundle projects/example` to see the file names, their SHA-256 hashes, and a manifest hash. Review each file with `/preview projects/example/FILENAME`, then use the displayed `/publish_bundle projects/example MANIFEST_HASH` command. The contents and relative paths are rechecked before any GitHub request; changed, added, removed, or renamed files require a new preview. One draft PR contains all the captured files under a unique `contributions/` directory, preserving their relative paths. A bundle accepts up to eight UTF-8 files, 20 KB per file and 100 KB total; hidden paths, symlinks, binary files, and case-insensitive duplicate paths are rejected. If publishing fails, the branch may contain only some files; inspect the named branch before retrying. The manifest is a snapshot check, not a substitute for reviewing each file.

## Static blog draft

Ask MiniAgent to write research notes as text files, then ask it to build a blog from the chosen drafts. The `build_blog` tool creates a self-contained `site/index.html` in the workspace, escaping draft text and requiring no server-side code or external assets. Review its source through `/preview site/index.html`, or copy the file from the VM to view it in a browser. To propose it as the stable repository homepage, send the `/publish_site SHA256` command shown in the preview. It opens a draft PR that creates or replaces **root `index.html`** on a new branch; review the diff before merging. Each new page replaces the previous homepage, so include all notes you want to retain when regenerating it. A repository configured to [publish GitHub Pages from the root of its default branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) can serve it at the Pages root after you merge the PR and GitHub builds the site. Pages availability depends on your GitHub plan and repository; Pages sites are public. Neither the generator nor the draft PR changes Pages settings or merges the branch. Live GitHub and Pages behavior remains unverified.

## Roadmap

1. Test both real provider integrations, tool calling, accounting and failure handling against low spending limits.
2. Improve recurring objectives with per-objective budgets, retries, and better progress and failure reporting.
3. Verify and harden Linux test isolation on the target VM; verify the GitHub workflow against a real repository.
4. Verify the homepage workflow on GitHub Pages; add citation checking and outcome-based evaluations before enabling continuous self-improvement.
