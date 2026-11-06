"""Command-line entry point and private Telegram long-polling controller."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .agent import Agent
from .config import Config
from .tools import handle, SCHEMAS
from .queue import Queue
from .budget import Budget, BudgetExceeded
from .provider import ProviderError
from .github import configured_github, read_draft, read_bundle, GitHubError


def telegram_api(token, method, data, timeout=40):
    request = Request('https://api.telegram.org/bot' + token + '/' + method,
                      data=json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise RuntimeError('Telegram request failed')
    return result['result']


def job_tool_handler(queue, budget, job_id, abort_event=None):
    def dispatch(name, args):
        if abort_event and abort_event.is_set():
            raise RuntimeError('Task execution was aborted by user.')
        if name == 'propose_question':
            try:
                ident = queue.propose_question(job_id, args.get('question', ''), args.get('context', ''))
                return f'Question {ident} proposed to the user; it will be presented after this specialist run.'
            except ValueError as exc:
                return 'Question rejected: ' + str(exc)
        if name != 'propose_followup':
            return handle(name, args)
        spent, limit = budget.today()
        if spent * 4 >= limit * 3:
            return 'Follow-up deferred: background budget threshold reached.'
        try:
            ident = queue.propose_followup(job_id, args.get('task'))
            return f'Follow-up {ident} proposed; it will be queued only if this task succeeds.'
        except ValueError as exc:
            return 'Follow-up rejected: ' + str(exc)
    return dispatch


def task_error_message(exc):
    if isinstance(exc, (BudgetExceeded, ProviderError)):
        return 'Task stopped: ' + str(exc)
    return 'Task failed. Check service logs and configuration; no automatic task retry was attempted.'


def parse_job_id(parts):
    if len(parts) != 2 or not parts[1].isdigit() or len(parts[1]) > 18 or int(parts[1]) < 1:
        raise ValueError('Invalid task ID')
    return int(parts[1])


def telegram_chunks(message, max_units=3500):
    """Keep messages below Telegram's limit even for supplementary Unicode."""
    chunk, units = [], 0
    for character in message:
        cost = 2 if ord(character) > 0xFFFF else 1
        if units + cost > max_units:
            yield ''.join(chunk)
            chunk, units = [], 0
        chunk.append(character)
        units += cost
    if chunk:
        yield ''.join(chunk)


def telegram_loop(config):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    user = os.environ.get('TELEGRAM_USER_ID', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not user.isdigit() or not chat.lstrip('-').isdigit():
        raise SystemExit('Set TELEGRAM_BOT_TOKEN, numeric TELEGRAM_USER_ID and TELEGRAM_CHAT_ID.')
    state = Path(os.environ.get('MINIAGENT_STATE_DIR', '/var/lib/miniagent'))
    state.mkdir(parents=True, exist_ok=True)
    offset_file = state / 'telegram-offset'
    queue = Queue(config.db_path)
    if offset_file.exists():
        queue.migrate_offset(int(offset_file.read_text().strip()))
    queue.recover()
    queue.seed_learning()
    budget = Budget(config.db_path, config.daily_usd)
    stop_event = threading.Event()
    try:
        import signal
        signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())
    except (ValueError, AttributeError):
        pass
    active_aborts = {}
    def send(message, reply_markup=None):
        chunks = list(telegram_chunks(message))
        for i, chunk in enumerate(chunks):
            payload = {'chat_id': int(chat), 'text': chunk}
            if reply_markup and i == len(chunks) - 1:
                payload['reply_markup'] = reply_markup
            telegram_api(token, 'sendMessage', payload)
    def worker():
        while not stop_event.is_set():
            try:
                spent, limit = budget.today()
                from .pacing import calculate_pacing
                pacing = calculate_pacing(spent, limit)
                # Preserve some budget for user-directed work and respect pacing status
                background_allowed = spent * 4 < limit * 3 and pacing['status'] != 'hot'
                if background_allowed:
                    queue.schedule_due()
                job = queue.claim(allow_background=background_allowed)
                if job:
                    ident, task = job
                    abort_ev = threading.Event()
                    active_aborts[ident] = abort_ev
                    start_time = time.time()
                    tool_calls_counter = [0]
                    base_handler = job_tool_handler(queue, budget, ident, abort_event=abort_ev)
                    def counted_tool_handler(name, args):
                        tool_calls_counter[0] += 1
                        return base_handler(name, args)
                    try:
                        agent_config = config
                        if pacing['status'] in ('hot', 'warm'):
                            from dataclasses import replace
                            agent_config = replace(config, max_tool_rounds=min(config.max_tool_rounds, pacing['recommended_max_tool_rounds']))
                        agent = Agent(agent_config, tool_handler=counted_tool_handler, tool_schemas=SCHEMAS)
                        result = agent.run_task(task)
                        duration = int((time.time() - start_time) * 1000)
                        queue.finish(ident, str(result) or 'No text response.', duration_ms=duration, tool_calls_count=tool_calls_counter[0])
                    except Exception as exc:
                        duration = int((time.time() - start_time) * 1000)
                        print('Task failed:', type(exc).__name__, file=sys.stderr, flush=True)
                        queue.finish(ident, task_error_message(exc), failed=True, error_type=type(exc).__name__, duration_ms=duration, tool_calls_count=tool_calls_counter[0])
                    finally:
                        active_aborts.pop(ident, None)
                else:
                    stop_event.wait(2)
            except Exception as exc:
                print('Worker failed:', type(exc).__name__, file=sys.stderr, flush=True)
                stop_event.wait(10)
    threading.Thread(target=worker, daemon=True).start()
    while not stop_event.is_set():
        try:
            for ident, state_name, result in queue.pending_notifications():
                send(f'Task {ident} ({state_name}):\n{result}')
                queue.mark_notified(ident)
            for q_id, q_text, q_ctx, q_job in queue.open_questions(unnotified=True):
                btn = {'inline_keyboard': [[{'text': '❌ Cancel Task', 'callback_data': f'/cancel {q_job}'}]]}
                send(f'Question for Task {q_job} (Question ID: {q_id}):\n{q_text}\n\nContext: {q_ctx}\n\nReply with: /answer {q_id} YOUR_ANSWER', reply_markup=btn)
                queue.mark_question_notified(q_id)
            updates = telegram_api(token, 'getUpdates', {'offset': queue.offset(), 'timeout': 10, 'allowed_updates': ['message', 'callback_query']})
            for update in updates:
                update_id = update['update_id']
                cb = update.get('callback_query')
                if cb:
                    cb_from = str(cb.get('from', {}).get('id'))
                    if cb_from == user:
                        try:
                            telegram_api(token, 'answerCallbackQuery', {'callback_query_id': cb.get('id')})
                        except Exception:
                            pass
                        cb_data = cb.get('data', '').strip()
                        if cb_data.startswith('/'):
                            message = {'text': cb_data, 'from': {'id': int(user)}, 'chat': {'id': int(chat), 'type': 'private'}}
                        else:
                            queue.ingest(update_id)
                            continue
                    else:
                        queue.ingest(update_id)
                        continue
                else:
                    message = update.get('message', {})
                if (str(message.get('from', {}).get('id')) != user or
                    str(message.get('chat', {}).get('id')) != chat or
                    message.get('chat', {}).get('type') != 'private'):
                    queue.ingest(update_id)
                    continue
                task = message.get('text', '').strip()
                if not task:
                    queue.ingest(update_id)
                    continue
                if task.startswith('/'):
                    # Commands are acknowledged before execution and may need resending after a crash.
                    if update_id < queue.offset():
                        continue
                    queue.ingest(update_id)
                    parts = task.split(maxsplit=2)
                    command = parts[0].split('@')[0].lower()
                    if command in ('/start', '/help'):
                        send('Send a task as a message. Commands: /status, /health, /budget, /jobs, /job ID, /cancel ID, /questions, /answer ID TEXT, /pause, /resume, /schedule HOURS TASK, /objectives, /unschedule ID, /preview PATH, /publish PATH SHA256, /publish_site SHA256, /preview_bundle DIR, /publish_bundle DIR SHA256. Recurring tasks start after the interval, minimum 6 hours.')
                    elif command == '/status':
                        spent, limit = budget.today()
                        send(f"{'Paused' if queue.paused() else 'Running'}; jobs: {queue.counts()}; recurring objectives: {len(queue.objectives())}; model ledger today (UTC): ${spent/1e6:.4f} / ${limit/1e6:.2f}.")
                    elif command == '/health':
                        from .health import collect
                        from .tools import ROOT
                        send('Resource snapshot (null means unavailable or no numeric limit):\n' + json.dumps(collect(ROOT), indent=2))
                    elif command == '/budget':
                        spent, limit = budget.today()
                        usage, truncated = budget.usage_today()
                        lines = [f'UTC model ledger: ${spent/1e6:.6f} / ${limit/1e6:.2f} (estimated; not provider invoice).']
                        for row in usage:
                            label = ' '.join(row['model'].split())[:120]
                            tier = ' '.join(row['tier'].split())[:40]
                            cache = (f"{row['cached_tokens']} cached input tokens reported in {row['cache_reported_requests']}/{row['requests']} requests"
                                     if row['cache_reported_requests'] else 'cache usage not reported')
                            lines.append(f"{label} [{tier}]: ${row['committed_microdollars']/1e6:.6f}; {row['requests']} requests; "
                                         f"{row['input_tokens']} input and {row['output_tokens']} output tokens; {cache}; "
                                         f"{row['unsettled_requests']} unsettled reservations.")
                        if truncated:
                            lines.append('Additional model groups omitted; total includes all groups.')
                        send('\n'.join(lines))
                    elif command == '/jobs':
                        jobs = queue.recent_jobs()
                        send('\n'.join(f"{ident} [{state_name}, {origin}] {' '.join(text.split())[:120]}" for ident, state_name, origin, text in jobs) or 'No tasks yet.')
                    elif command == '/job':
                        try:
                            job = queue.get_job(parse_job_id(parts))
                            if job:
                                ident, state_name, origin, task_text, result = job
                                send(f'Task {ident} [{state_name}, {origin}]\n\nRequest: {task_text}\n\nResult: {result or "Not available yet."}')
                            else:
                                send('Task not found.')
                        except ValueError:
                            send('Use /job ID with a valid positive task ID.')
                    elif command == '/cancel':
                        try:
                            target_id = parse_job_id(parts)
                            state_name = queue.cancel_job(target_id)
                            if state_name == 'cancelled':
                                send('Task cancelled before execution. Recurring objectives remain scheduled; use /unschedule ID to stop future runs.')
                            elif state_name == 'not_found':
                                send('Task not found.')
                            else:
                                if target_id in active_aborts:
                                    active_aborts[target_id].set()
                                    send(f'Task {target_id} is running; cancellation requested and next step will halt.')
                                else:
                                    send(f'Task was not cancelled; its state is {state_name}. Running tasks cannot be stopped.')
                        except ValueError:
                            send('Use /cancel ID with a valid positive task ID.')
                    elif command == '/questions':
                        questions = queue.open_questions()
                        if not questions:
                            send('No open questions.')
                        else:
                            send('\n\n'.join(f'Question {q_id} (Task {q_job}):\n{q_text}\nContext: {q_ctx}\nReply: /answer {q_id} YOUR_ANSWER' for q_id, q_text, q_ctx, q_job in questions))
                    elif command == '/answer':
                        try:
                            if len(parts) < 3 or not parts[1].isdigit():
                                raise ValueError('Use /answer ID YOUR_ANSWER')
                            q_id = int(parts[1])
                            answer_text = parts[2]
                            new_job = queue.answer_question(q_id, answer_text)
                            send(f'Answer accepted. Continuing task as job {new_job}.')
                        except (IndexError, ValueError) as exc:
                            send(str(exc) if isinstance(exc, ValueError) else 'Use /answer ID YOUR_ANSWER with a valid question ID.')
                    elif command in ('/pause', '/resume'):
                        queue.pause(command == '/pause')
                        send('Paused: queued work will wait; an in-flight task cannot be stopped.' if command == '/pause' else 'Resumed queued and recurring work.')
                    elif command == '/history':
                        try:
                            if len(parts) > 1 and parts[1].isdigit():
                                target_id = int(parts[1])
                                entries = queue.get_history(job_id=target_id)
                                if not entries:
                                    send(f'No history found for Task {target_id}.')
                                else:
                                    h = entries[0]
                                    dur = f'{h[7]/1000:.1f}s' if h[7] else 'N/A'
                                    send(f'Task {h[1]} History:\nState: {h[4]}\nOrigin: {h[3]}\nDuration: {dur}\nTool Calls: {h[9]}\nError: {h[10] or "None"}\nExcerpt: {h[8]}')
                            else:
                                entries = queue.get_history(limit=5)
                                if not entries:
                                    send('No task history recorded.')
                                else:
                                    lines = []
                                    for h in entries:
                                        dur = f'{h[7]/1000:.1f}s' if h[7] else 'N/A'
                                        err = f' [{h[10]}]' if h[10] else ''
                                        lines.append(f'#{h[1]} ({h[4]}): "{h[2][:45]}" — {dur}{err}')
                                    send('Recent Task History:\n' + '\n'.join(lines) + '\n\nSend /history ID for details.')
                        except Exception as exc:
                            send('Could not read task history: ' + type(exc).__name__)
                    elif command == '/postmortem':
                        try:
                            from .postmortem import generate_postmortem_report
                            send(generate_postmortem_report(queue))
                        except Exception as exc:
                            send('Postmortem analysis failed: ' + type(exc).__name__)
                    elif command == '/diagram':
                        try:
                            from .diagram import generate_mermaid_diagram
                            send(generate_mermaid_diagram(queue, budget))
                        except Exception as exc:
                            send('Could not generate diagram: ' + type(exc).__name__)
                    elif command == '/objectives':
                        objectives = queue.objectives()
                        send('\n'.join(f'{i}: every {seconds // 3600}h — {text}' for i, text, seconds, _ in objectives) or 'No recurring objectives.')
                    elif command == '/unschedule':
                        try:
                            removed = queue.remove_objective(int(parts[1]))
                            send('Objective removed.' if removed else 'Objective not found.')
                        except (IndexError, ValueError):
                            send('Use /unschedule ID.')
                    elif command == '/schedule':
                        try:
                            ident = queue.add_objective(parts[2], int(parts[1]))
                            send(f'Objective {ident} saved. Its first run is after the interval.')
                        except (IndexError, ValueError):
                            send('Use /schedule HOURS TASK; HOURS must be 6–720. Maximum five objectives and 3,000 task bytes.')
                    elif command == '/preview':
                        try:
                            path = parts[1]
                            name, content, digest = read_draft(path)
                            site_hint = f'\nFor the repository homepage: /publish_site {digest}' if path == 'site/index.html' else ''
                            send(f'Draft {path}\nSHA-256: {digest}\n\n{content.decode("utf-8")}\n\nTo open a draft PR, send /publish {path} {digest}{site_hint}')
                        except (IndexError, ValueError, OSError, UnicodeError):
                            send('Could not read draft. Use /preview PATH with a UTF-8 draft path without spaces.')
                    elif command == '/publish':
                        try:
                            url = configured_github().publish(parts[1], parts[2])
                            send('Draft pull request created: ' + url)
                        except (IndexError, ValueError, OSError, UnicodeError, GitHubError) as exc:
                            send('Publish failed: ' + (str(exc)[:400] if isinstance(exc, (ValueError, GitHubError)) else 'Check path and configuration.'))
                    elif command == '/publish_site':
                        try:
                            url = configured_github().publish_site(parts[1])
                            send('Homepage draft pull request created: ' + url)
                        except (IndexError, ValueError, OSError, UnicodeError, GitHubError) as exc:
                            send('Homepage draft failed: ' + (str(exc)[:400] if isinstance(exc, (ValueError, GitHubError)) else 'Check configuration and preview the page.'))
                    elif command == '/preview_bundle':
                        try:
                            directory = parts[1]
                            _, manifest, digest = read_bundle(directory)
                            listing = '\n'.join(f"{item['path']}  {item['sha256']}" for item in manifest)
                            send(f'Bundle {directory}\n{listing}\n\nManifest SHA-256: {digest}\nReview each file with /preview {directory}/PATH. To open a draft PR: /publish_bundle {directory} {digest}')
                        except (IndexError, ValueError, OSError, UnicodeError) as exc:
                            send('Bundle preview failed: ' + (str(exc)[:300] if isinstance(exc, ValueError) else 'Check directory and contents.'))
                    elif command == '/publish_bundle':
                        try:
                            url = configured_github().publish_bundle(parts[1], parts[2])
                            send('Draft pull request created: ' + url)
                        except (IndexError, ValueError, OSError, UnicodeError, GitHubError) as exc:
                            send('Publish failed: ' + (str(exc)[:400] if isinstance(exc, (ValueError, GitHubError)) else 'Check directory and configuration.'))
                    else:
                        send('Unknown command. Use /help.')
                    continue
                if len(task.encode('utf-8')) > 3000:
                    queue.ingest(update_id)
                    send('Please send a task shorter than 3,000 UTF-8 bytes.')
                    continue
                ident = queue.ingest(update_id, task)
                if ident is not None:
                    send(f'Task {ident} queued. I will send its result here.')
                else:
                    send('Queue full or update already processed. Please check /status.')
        except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            # Do not log exception text: HTTP clients may include the bot-token URL.
            print('Telegram polling failed:', type(exc).__name__, file=sys.stderr, flush=True)
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description='MiniAgent')
    parser.add_argument('mode', choices=['telegram', 'task', 'doctor', 'eval-planner', 'history', 'postmortem', 'diagram'])
    parser.add_argument('text', nargs='?', help='Task text for task mode')
    parser.add_argument('--live', action='store_true', help='Run paid model requests for doctor or planner evaluation')
    parser.add_argument('--network', action='store_true', help='Check external endpoints and metadata-port exposure in doctor mode')
    args = parser.parse_args()
    config = Config.from_env()
    if args.network and args.mode != 'doctor':
        parser.error('--network is only valid in doctor mode')
    if args.live and args.mode not in ('doctor', 'eval-planner'):
        parser.error('--live is only valid in doctor or eval-planner mode')
    if args.mode == 'telegram':
        telegram_loop(config)
    elif args.mode == 'diagram':
        from .diagram import generate_mermaid_diagram
        from .budget import Budget
        queue = Queue(config.db_path)
        budget = Budget(config.db_path, config.daily_usd)
        print(generate_mermaid_diagram(queue, budget))
    elif args.mode == 'history':
        queue = Queue(config.db_path)
        history = queue.get_history(limit=20)
        if not history:
            print('No task history recorded.')
        for h in history:
            dur = f'{h[7]/1000:.1f}s' if h[7] else 'N/A'
            err = f' [{h[10]}]' if h[10] else ''
            print(f'#{h[1]} ({h[4]}, {h[3]}): "{h[2][:60]}" — {dur}{err}')
    elif args.mode == 'postmortem':
        from .postmortem import generate_postmortem_report
        queue = Queue(config.db_path)
        print(generate_postmortem_report(queue))
    elif args.mode == 'doctor':
        if args.text:
            parser.error('doctor does not accept task text')
        from .doctor import diagnose
        checks = diagnose(config, live=args.live, network=args.network)
        for check in checks:
            label = 'WARN' if check.get('warning') else ('OK' if check['ok'] else 'FAIL')
            print(label + ' ' + check['check'] + ': ' + check['detail'])
        if any(not check['ok'] for check in checks):
            raise SystemExit(1)
    elif args.mode == 'eval-planner':
        if args.text or not args.live:
            parser.error('eval-planner requires --live and no task text; it makes up to eight paid model requests')
        from dataclasses import replace
        from .evaluation import evaluate_planner
        agent = Agent(replace(config, planner_enabled=True))
        report = evaluate_planner(agent, agent.provider.budget)
        print(json.dumps(report, indent=2))
        if report['error']:
            raise SystemExit(1)
    else:
        if not args.text:
            parser.error('task requires text')
        print(Agent(config, tool_handler=handle, tool_schemas=SCHEMAS).run_task(args.text))


if __name__ == '__main__':
    main()
