# Running MiniAgent on a Google Cloud e2-micro

This guide assumes a Debian or Ubuntu Linux VM, outbound internet access, Python 3, and that you already uploaded the project zip. The agent uses Telegram long polling, so it does not need an inbound web port. Commands below run **on your VM**, in the SSH terminal opened from Google Cloud Console. Do not paste API keys into chat, GitHub, or screenshots.

## 1. Check costs first

Your e2-micro has 1 GiB RAM, two shared vCPUs, and a 30 GB disk. The CPUs share a smaller baseline allocation; two vCPUs do not mean two fully dedicated CPU cores. Google Cloud's free-tier allowance applies only when all published conditions are met; region, disk type and size, outbound traffic, external IP addresses and other resources can change your bill. See [machine specifications](https://cloud.google.com/compute/docs/general-purpose-machines), [Google Cloud Free Program](https://cloud.google.com/free/docs/free-cloud-features), and [Compute pricing](https://cloud.google.com/products/compute/pricing/general-purpose). The model provider bills separately from Google Cloud. Make a [Cloud Billing budget](https://cloud.google.com/billing/docs/how-to/budgets) and provider-side spending limit where offered. An ordinary Google budget is an **alert**, not an automatic spending stop. A model budget in MiniAgent applies only to the usage it tracks; it cannot cap the VM, networking, taxes, other applications, or a provider's own charges. Check actual invoices and usage. Avoid sharing the same model key with other apps.

## 2. Make a private Telegram bot

1. In Telegram, use the official [@BotFather](https://t.me/BotFather), issue `/newbot`, and follow its instructions. Treat the resulting bot token like a password.
2. Open your bot's private chat and send `/start`. The bot cannot initiate a conversation until you message it first.
3. After uploading and unpacking the project, run `python3 deploy/telegram_chat_id.py` from the project directory. Enter the token when prompted; it will not be echoed. Note the private chat ID and user ID and verify the displayed username is yours. The service checks both values; do not add a group chat ID. If there are no messages, try again after `/start`. If the service is already running, stop it first: only one process should poll this bot at a time.
4. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`, and `TELEGRAM_CHAT_ID` in the protected configuration described below. An allowlist is essential: anyone who discovers a bot username can send it messages.

If a token leaks, revoke it using BotFather and immediately update the configuration. See the official [Telegram bot FAQ](https://core.telegram.org/bots/faq) and [Bot API](https://core.telegram.org/bots/api).

## 3. Install the files

Install packages, configure swap, and create the dedicated, unprivileged account:

```sh
sudo apt-get update
sudo apt-get install -y python3 unzip ca-certificates iptables-persistent

# Create a 1 GiB swapfile to prevent out-of-memory kills on the 1 GiB e2-micro
if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin miniagent
sudo install -d -o root -g root -m 0755 /opt/miniagent
```

Upload the project zip through the SSH window's file-upload function (or `gcloud compute scp`). Unpack it under `/opt/miniagent`. For example, if the zip is in your SSH home directory and is named `MiniAgent.zip`:

```sh
sudo unzip ~/MiniAgent.zip -d /opt/miniagent
ls /opt/miniagent
```

The `miniagent` Python package and the `deploy` directory must be directly under `/opt/miniagent`; if the zip contains an enclosing folder, adjust the extraction accordingly. Make application files owned by root, so the running agent cannot silently rewrite its own service or harness. Never unzip credentials into this directory. The service gets a separate private writable state directory at `/var/lib/miniagent`.

```sh
sudo chown -R root:root /opt/miniagent
sudo chmod -R go-w /opt/miniagent
```

## 4. Configure and start

Follow the main README's provider configuration and pricing instructions, and put all required environment variables in `/etc/miniagent.env`. Do not copy placeholder prices into production: unknown or stale prices make any model cost guard unreliable. Set the database path to `/var/lib/miniagent/state.db`, and start with a conservative model budget below $1 to leave room for all other costs. Environment files use one `NAME=value` entry per line; protect the file before writing secrets:

```sh
sudo install -o root -g root -m 0600 /dev/null /etc/miniagent.env
sudo nano /etc/miniagent.env
sudo install -o root -g root -m 0644 /opt/miniagent/deploy/miniagent.service /etc/systemd/system/miniagent.service
sudo systemctl daemon-reload
sudo systemctl enable --now miniagent.service
sudo systemctl status miniagent.service --no-pager
```

To check workspace permissions, the budget ledger, and configuration under the service account without making network calls, run:

```sh
sudo systemd-run --wait --pipe --collect --property=User=miniagent --property=WorkingDirectory=/opt/miniagent --property=EnvironmentFile=/etc/miniagent.env /usr/bin/python3 -m miniagent doctor
```

To additionally send one small test request to each configured model, append `--live` to that command. These requests are paid and use the same model budget ledger. The live check verifies basic model responses and the requested Flex tier; it does not test model tool calling, Telegram, GitHub, or the actual systemd sandbox. Flex can be unavailable, so a failed probe may require trying again later. The diagnostic does not print keys or model response text. It creates the ledger if it does not yet exist and briefly creates a temporary file to test workspace permissions.

Append `--network` to the same command to check reachability of the public GitHub, Wikipedia and arXiv APIs, verify the Telegram token with `getMe` (without sending a message), and check whether the cloud metadata server's HTTP port can be reached. This does not use model tokens. It prints a warning if metadata is reachable but does not retrieve a cloud access token. `--network` and `--live` can be used together. This transient service runs as the same user but does not reproduce every restriction of `miniagent.service`, so verify security controls in the actual service too.

To measure the experimental planner's routing on eight synthetic cases, run the following. It makes up to eight paid primary-model requests under the shared model budget; it does not execute the sample tasks. The results are a limited routing check, not proof that enabling the planner improves quality or saves money.

```sh
sudo systemd-run --wait --pipe --collect --property=User=miniagent --property=WorkingDirectory=/opt/miniagent --property=EnvironmentFile=/etc/miniagent.env /usr/bin/python3 -m miniagent eval-planner --live
```

Set the Telegram IDs to the verified chat and user values, plus the bot token, and include the model settings listed in the main README. Only the root-owned systemd service can read the configuration file. The service runs as the unprivileged `miniagent` account, starts at boot, uses outbound Telegram polling, and has a 400 MiB memory ceiling to preserve room for the OS. It does not open a public server. If the service fails:

```sh
sudo journalctl -u miniagent.service -n 100 --no-pager
sudo systemctl restart miniagent.service
```

Do not post logs without checking for private information. Edit `/etc/miniagent.env` using `sudo nano`, then restart the service to apply changes. Stop it with `sudo systemctl stop miniagent.service`. To prevent automatic restarts at boot, also run `sudo systemctl disable miniagent.service`.

## 5. GitHub and isolation

Use a **separate repository** and a fine-grained, short-lived token restricted to that repository. The optional setup and `/preview` and `/publish` commands are in the main README. Do not expose private keys in repository files, commits, Telegram, or model prompts. Review generated changes before publishing or running them; a pull request to a public repository is publicly visible. Disable or restrict GitHub Actions and other automatic workflows that could run on pull requests before enabling this feature.

MiniAgent does not need Google Cloud API permissions to use its model, research, Telegram, and GitHub features. On Compute Engine, an attached service account may be able to issue credentials through the metadata server to processes on the VM. Check which service account is attached and what access it has; use no service account when feasible, or a dedicated least-privilege account.

To explicitly block the `miniagent` user from reaching the cloud metadata IP (`169.254.169.254`), apply an iptables rule:

```sh
sudo iptables -A OUTPUT -m owner --uid-owner miniagent -d 169.254.169.254 -j DROP
sudo netfilter-persistent save
``` Changing or removing an account can affect other VM features, such as logging or monitoring, so check those dependencies first. Google also documents restricting metadata access by Linux user using the host firewall. Do not block all traffic to the metadata IP without checking DNS and guest-agent dependencies. See [Google's service-account security guidance](https://cloud.google.com/iam/docs/best-practices-service-accounts) and [metadata overview](https://cloud.google.com/compute/docs/metadata/overview). The experimental sandbox's isolated network is a separate layer, not proof against a kernel escape.

The systemd settings are useful hardening, not an isolation boundary for hostile code. The optional experimental Python test runner is disabled by default and described in the README; it uses Linux namespaces and limits, but shares the host kernel and is not a complete security boundary. Avoid running hostile or sensitive workloads on the VM, keep it patched, and use stronger disposable isolation when needed. An autonomous agent that can run arbitrary shell commands, install packages, modify its harness, or reach its credentials can leak secrets or accrue costs. Web pages, repository content, and Telegram messages can contain instructions that attempt to redirect the agent; treat them as untrusted data.

## Upgrades and backups

Stop the service before replacing app files, retain a copy of the old release, and restart it afterward. Back up `/var/lib/miniagent` securely: its database may contain messages and cost history. Keep `/etc/miniagent.env` out of the project zip and version control. Reinstalling or deleting the ledger may reset local cost accounting, so check provider usage before starting again.

