"""Publish a specifically reviewed draft as a GitHub draft pull request."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .tools import MAX_FILE, safe_path


class GitHubError(RuntimeError):
    pass


class GitHubNotFound(GitHubError):
    pass


def read_draft(path):
    target = safe_path(path)
    # Resolve and read once, then publish these exact bytes after a hash check.
    data = target.read_bytes()
    if len(data) > MAX_FILE:
        raise ValueError('Draft too large')
    data.decode('utf-8')
    return target.name, data, hashlib.sha256(data).hexdigest()


def read_bundle(path):
    """Snapshot at most eight UTF-8 files and hash their paths and exact bytes."""
    root = safe_path(path)
    if not root.is_dir():
        raise ValueError('Bundle must be a workspace directory')
    files, total, seen, directories = [], 0, set(), 0
    def fail_walk(error):
        raise error
    for current, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
        directories += 1
        if directories > 32:
            raise ValueError('Too many directories in bundle')
        for directory in dirs:
            if (Path(current) / directory).is_symlink() or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', directory):
                raise ValueError('Bundle has a symlink or invalid directory name')
        for name in names:
            target = Path(current) / name
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', name):
                raise ValueError('Bundle has an invalid file name')
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise ValueError('Bundle requires regular UTF-8 files under 20 KB')
            relative = target.relative_to(root).as_posix()
            if len(relative) > 240 or relative.casefold() in seen:
                raise ValueError('Bundle has a duplicate or too-long path')
            seen.add(relative.casefold())
            content = target.read_bytes()
            content.decode('utf-8')
            total += len(content)
            if len(content) > MAX_FILE or total > 100000 or len(files) >= 8:
                raise ValueError('Bundle exceeds the size or eight-file limit')
            files.append((relative, content))
    if not files:
        raise ValueError('Bundle has no files')
    files.sort(key=lambda item: item[0])
    manifest = [{'path': name, 'sha256': hashlib.sha256(content).hexdigest()} for name, content in files]
    encoded = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return files, manifest, hashlib.sha256(encoded).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repo, token):
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}', repo or ''):
            raise ValueError('Set MINIAGENT_GITHUB_REPO to owner/repository')
        if not token or '\n' in token or '\r' in token:
            raise ValueError('Set MINIAGENT_GITHUB_TOKEN')
        self.repo, self.token = repo, token

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        req = Request('https://api.github.com/repos/' + self.repo + path, data=data, method=method,
                      headers={'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + self.token,
                               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'MiniAgent',
                               'Content-Type': 'application/json'})
        try:
            with build_opener(NoRedirect()).open(req, timeout=30) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise GitHubError('GitHub response too large')
            return json.loads(raw)
        except GitHubError:
            raise
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code == 404:
                raise GitHubNotFound('GitHub resource not found.') from None
            raise GitHubError(f'GitHub request failed (HTTP {code}).') from None
        except Exception as exc:
            # Never return HTTP response bodies, request headers, or credentials.
            raise GitHubError('GitHub request failed (' + type(exc).__name__ + ').') from None

    def publish(self, path, expected_hash):
        name, content, digest = read_draft(path)
        if not re.fullmatch(r'[0-9a-f]{64}', expected_hash or '') or digest != expected_hash:
            raise ValueError('Draft changed or hash is invalid; preview it again.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', name) or name.startswith('.'):
            raise ValueError('Draft filename must contain only letters, numbers, dot, underscore or hyphen.')
        return self._publish_files([(name, content)], name, digest, 'SHA-256')

    def publish_bundle(self, path, expected_hash):
        files, manifest, digest = read_bundle(path)
        if not re.fullmatch(r'[0-9a-f]{64}', expected_hash or '') or digest != expected_hash:
            raise ValueError('Bundle changed or hash is invalid; preview it again.')
        return self._publish_files(files, 'project bundle', digest, 'Manifest SHA-256')

    def publish_site(self, expected_hash):
        _, content, digest = read_draft('site/index.html')
        if not re.fullmatch(r'[0-9a-f]{64}', expected_hash or '') or digest != expected_hash:
            raise ValueError('Homepage changed or hash is invalid; preview it again.')
        return self._publish_files([('index.html', content)], 'homepage', digest, 'SHA-256', homepage=True)

    def publish_update(self, path, expected_hash, direct_commit=False):
        """Publish a daily or weekly update file to updates/ either via Draft PR or direct commit."""
        name, content, digest = read_draft(path)
        if not re.fullmatch(r'[0-9a-f]{64}', expected_hash or '') or digest != expected_hash:
            raise ValueError('Update file changed or hash is invalid; preview it again.')
        rel_path = path.replace('\\', '/')
        if not re.fullmatch(r'updates/(?:daily|weekly)/[A-Za-z0-9_.-]+\.md', rel_path):
            raise ValueError('Update file must be in updates/daily/ or updates/weekly/')

        info = self.request('GET', '')
        base = info['default_branch']
        head = self.request('GET', '/git/ref/heads/' + quote(base, safe=''))['object']['sha']

        existing_sha = None
        try:
            existing = self.request('GET', '/contents/' + quote(rel_path, safe='/') + '?ref=' + quote(head, safe=''))
            if existing is not None:
                existing_sha = existing.get('sha')
        except GitHubNotFound:
            existing_sha = None

        if direct_commit:
            payload = {'message': f'Post autonomous update: {rel_path}',
                       'branch': base,
                       'content': base64.b64encode(content).decode('ascii')}
            if existing_sha:
                payload['sha'] = existing_sha
            res = self.request('PUT', '/contents/' + quote(rel_path, safe='/'), payload)
            commit_url = res.get('commit', {}).get('html_url', '')
            return commit_url or f'https://github.com/{self.repo}/blob/{base}/{rel_path}'
        else:
            branch = 'miniagent/update-' + uuid4().hex
            try:
                self.request('POST', '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': head})
                payload = {'message': f'Add autonomous update: {rel_path}',
                           'branch': branch,
                           'content': base64.b64encode(content).decode('ascii')}
                if existing_sha:
                    payload['sha'] = existing_sha
                self.request('PUT', '/contents/' + quote(rel_path, safe='/'), payload)
                pr = self.request('POST', '/pulls', {
                    'title': f'MiniAgent update: {rel_path}',
                    'head': branch, 'base': base, 'draft': True,
                    'body': f'Autonomous progress update: {rel_path}\n\nSHA-256: {digest}\n\nInspect telemetry and learnings before merging.'
                })
            except Exception as exc:
                raise GitHubError('Publish did not complete. Check GitHub for branch ' + branch + ' before retrying. ' + type(exc).__name__) from None
            url = pr.get('html_url', '')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.hostname != 'github.com' or not parsed.path.startswith('/' + self.repo + '/pull/'):
                raise GitHubError('Pull request response was unexpected. Check branch ' + branch + ' on GitHub.')
            return url

    def _publish_files(self, files, title, digest, digest_label, homepage=False):
        info = self.request('GET', '')
        base = info['default_branch']
        head = self.request('GET', '/git/ref/heads/' + quote(base, safe=''))['object']['sha']
        existing_sha = None
        if homepage:
            try:
                existing = self.request('GET', '/contents/index.html?ref=' + quote(head, safe=''))
            except GitHubNotFound:
                existing = None
            if existing is not None:
                existing_sha = existing.get('sha')
                if existing.get('type') != 'file' or not isinstance(existing_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', existing_sha):
                    raise GitHubError('Existing homepage is not a regular file; no branch was created.')
        branch = 'miniagent/draft-' + uuid4().hex
        destination = '' if homepage else 'contributions/' + branch.split('-')[-1] + '/'
        # No retry after a potentially billable/mutating request. Report branch for recovery.
        try:
            self.request('POST', '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': head})
            for name, content in files:
                payload = {'message': 'Add MiniAgent draft', 'branch': branch,
                           'content': base64.b64encode(content).decode('ascii')}
                if homepage and existing_sha:
                    payload['sha'] = existing_sha
                self.request('PUT', '/contents/' + quote(destination + name, safe='/'),
                             payload)
            pr = self.request('POST', '/pulls', {'title': 'MiniAgent draft: ' + title[:180],
                'head': branch, 'base': base, 'draft': True,
                'body': 'Generated draft for review. Verify contents, sources, and safety before merging or executing.\n\n' + digest_label + ': ' + digest})
        except Exception as exc:
            raise GitHubError('Publish did not complete. Check GitHub for branch ' + branch + ' before retrying. ' + type(exc).__name__) from None
        url = pr.get('html_url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'github.com' or not parsed.path.startswith('/' + self.repo + '/pull/'):
            raise GitHubError('Pull request response was unexpected. Check branch ' + branch + ' on GitHub.')
        return url


def configured_github():
    return GitHub(os.environ.get('MINIAGENT_GITHUB_REPO', ''), os.environ.get('MINIAGENT_GITHUB_TOKEN', ''))
