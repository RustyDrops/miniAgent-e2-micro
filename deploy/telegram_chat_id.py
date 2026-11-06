#!/usr/bin/env python3
"""Show private Telegram chat/user IDs for a bot without printing its token."""
import getpass
import json
import sys
import urllib.error
import urllib.request


def main():
    token = getpass.getpass('Telegram bot token (input hidden): ').strip()
    if not token or any(c.isspace() for c in token):
        print('Invalid token.', file=sys.stderr)
        return 1
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{token}/getUpdates',
            data=json.dumps({'timeout': 0, 'allowed_updates': ['message']}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
    except (urllib.error.URLError, ValueError, OSError):
        # Avoid printing exceptions: HTTP exceptions may contain the secret URL.
        print('Telegram request failed. Check the token and connection.', file=sys.stderr)
        return 1
    if not data.get('ok'):
        print('Telegram rejected the request.', file=sys.stderr)
        return 1
    chats = {}
    for update in data.get('result', []):
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        if chat.get('type') == 'private' and 'id' in chat and 'id' in sender:
            chats[(chat['id'], sender['id'])] = sender.get('username', '')
    if not chats:
        print('No private chats found. Send /start to the bot, then retry. Stop the bot service first if it is already polling.')
        return 0
    print('Private chats (verify the username is yours):')
    for (chat_id, user_id), username in chats.items():
        print(f'chat ID: {chat_id}   user ID: {user_id}   username: @{username}' if username
              else f'chat ID: {chat_id}   user ID: {user_id}   (no username)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
