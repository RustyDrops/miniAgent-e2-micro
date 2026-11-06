"""Local deployment checks and opt-in, budget-accounted model probes."""
from dataclasses import replace
from pathlib import Path
import os
import json
import shutil
import socket
import sys
import tempfile
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .budget import Budget
from .provider import ChatProvider


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint_reachable(url, telegram=False):
    """Test only fixed endpoints; never expose response or URL in diagnostics."""
    request = Request(url, headers={'User-Agent': 'MiniAgent/0.1 (diagnostic)'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(8193)
        if telegram:
            result = json.loads(raw)
            return result.get('ok') is True and result.get('result', {}).get('is_bot') is True
        return bool(raw)
    except Exception as exc:
        # HTTPError may own a network stream; never print its URL or body.
        if hasattr(exc, 'close'):
            exc.close()
        return False


def metadata_reachable():
    reachable = []
    for host in ('169.254.169.254', 'fd20:ce::254'):
        try:
            with socket.create_connection((host, 80), timeout=2):
                reachable.append(host)
        except OSError:
            pass
    return reachable


def diagnose(config, live=False, network=False):
    checks = []
    def record(name, ok, detail, warning=False):
        checks.append({'check': name, 'ok': ok, 'detail': detail, 'warning': warning})

    record('Python', sys.version_info >= (3, 10), 'Requires Python 3.10 or newer.')
    workspace = Path(os.environ.get('MINIAGENT_WORKSPACE', '/var/lib/miniagent/workspace'))
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=workspace) as test:
            test.write(b'ok')
        free = shutil.disk_usage(workspace).free // (1024 * 1024)
        record('Workspace', True, f'Writable; {free} MiB available on its filesystem.')
    except OSError:
        record('Workspace', False, 'Cannot write the workspace. Check the configured path and service permissions.')

    try:
        ledger = Budget(config.db_path, config.daily_usd)
        spent, limit = ledger.today()
        record('Budget ledger', True, f'UTC model ledger: ${spent / 1e6:.4f} committed of ${limit / 1e6:.2f}.')
    except Exception as exc:
        # Do not report database paths, arbitrary exception text or credentials.
        ledger = None
        record('Budget ledger', False, 'Unable to open the ledger (' + type(exc).__name__ + ').')

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    user = os.environ.get('TELEGRAM_USER_ID', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    telegram_ok = bool(token and user.isdigit() and chat.lstrip('-').isdigit())
    record('Telegram configuration', telegram_ok, 'Token and numeric IDs are present; ownership and connectivity are not checked.' if telegram_ok else 'Set the bot token and both numeric IDs.')

    tinyfish_key = os.environ.get('TINYFISH_API_KEY', '').strip()
    if tinyfish_key:
        record('TinyFish configuration', True, 'TINYFISH_API_KEY configured for free-tier web search & fetch.')
    else:
        record('TinyFish configuration', True, 'Not configured. Set TINYFISH_API_KEY for free live web search & fetch.', warning=True)

    try:
        secondary = config.secondary_from_env()
        record('Model configuration', True, 'Primary and optional reviewer configuration parsed.' if secondary else 'Primary configuration parsed; reviewer uses the primary model.')
    except (ValueError, TypeError):
        secondary = None
        record('Model configuration', False, 'Reviewer configuration is incomplete or invalid.')

    enabled = os.environ.get('MINIAGENT_ENABLE_SANDBOX') == '1'
    if enabled:
        present = sys.platform == 'linux' and Path('/usr/bin/bwrap').is_file() and Path('/usr/bin/python3').is_file()
        record('Sandbox prerequisites', present, 'Binary found; run the separate namespace smoke check on the VM.' if present else 'Enabled but Linux, bubblewrap, or /usr/bin/python3 is missing.')
    else:
        record('Sandbox', True, 'Disabled; generated code will not be executed.')

    if network:
        targets = [('GitHub public API', 'https://api.github.com/zen'),
                   ('Wikipedia API', 'https://en.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json'),
                   ('arXiv API', 'https://export.arxiv.org/api/query?id_list=2301.00001&max_results=1')]
        for label, url in targets:
            ok = endpoint_reachable(url)
            record(label, ok, 'Endpoint responded.' if ok else 'Endpoint unavailable or response rejected.')
        if telegram_ok:
            ok = endpoint_reachable('https://api.telegram.org/bot' + token + '/getMe', telegram=True)
            record('Telegram API', ok, 'Bot API accepted the token; chat ownership is not checked.' if ok else 'Bot API unavailable or token rejected.')
        addresses = metadata_reachable()
        if addresses:
            record('Cloud metadata exposure', True, 'Metadata port reachable from this diagnostic process; attached VM service-account credentials may be accessible. Review the VM security guide.', warning=True)
        else:
            record('Cloud metadata exposure', True, 'No metadata connection succeeded in this check; this does not prove isolation.')
    else:
        record('Network probes', True, 'Not run. Use doctor --network for public endpoint, Telegram, and metadata-port checks.')

    if live:
        if ledger is None:
            record('Live model probes', False, 'Skipped because the budget ledger is unavailable.')
        else:
            models = [('Primary model', config)]
            if secondary:
                models.append(('Reviewer model', secondary))
            for label, model_config in models:
                try:
                    provider = ChatProvider(replace(model_config, max_output_tokens=128), ledger)
                    message = provider.complete([{'role': 'user', 'content': 'Reply with the word OK.'}])
                    valid = (isinstance(message, dict) and message.get('role') == 'assistant' and
                             isinstance(message.get('content'), str) and bool(message['content'].strip()))
                    record(label, valid, 'API returned an assistant message.' if valid else 'API returned an unexpected message.')
                except Exception as exc:
                    record(label, False, 'Request failed (' + type(exc).__name__ + '); check provider billing and service logs.')
    else:
        record('Live model probes', True, 'Not run. Use doctor --live for up to two paid, budget-accounted requests.')
    return checks
