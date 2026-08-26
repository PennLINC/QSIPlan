"""Serve the explorer live: the tier-3 provider.

``qsiplan <bids> --serve`` keeps the indexed records in memory and answers
view requests by running the real compiler, so every control change on the
page is a millisecond round-trip to the same Python a qsiprep run would
execute - no JavaScript reimplementation, no drift. The page served is the
same explorer page the static generator writes; its embedded index doubles
as the page's cache and the ``/sub-<label>/view`` endpoint fills it on
demand. The endpoint's query string is exactly the canonical combined key
(:func:`~.methods.combined_key`), so combinations beyond the embedded grid -
future flags, curation what-ifs - cost nothing extra to support.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .explorer import build_for_policy, build_policy_grid, grouping_signature
from .interactive import explorer_view, render_explorer_html
from .metadata import index_subject
from .methods import parse_combined_key
from .models import GroupingPolicy


class ExplorerApp:
    """The server's request-independent core, kept apart from the HTTP layer.

    Indexes each subject lazily and only once, keeps the records and the
    deduped policy grid in memory, and answers view requests with the real
    compiler. One lock serializes all state access: every operation is
    milliseconds, and neither BIDSLayout nor the lazy caches are guaranteed
    thread-safe.
    """

    def __init__(
        self,
        layout,
        subjects,
        *,
        session_id=None,
        base_policy: GroupingPolicy | None = None,
        initial_selection=None,
    ):
        self._layout = layout
        self.subjects = list(subjects)
        self._session_id = session_id
        self._base_policy = base_policy if base_policy is not None else GroupingPolicy()
        self._initial_selection = initial_selection
        self._lock = threading.Lock()
        self._states = {}  # label -> (records, index_issues, PolicyGrid)

    def _state(self, label):
        """The (records, issues, grid) triple for one subject, indexed once."""
        if label not in self._states:
            if label not in self.subjects:
                raise KeyError(label)
            query = {
                'subject': label,
                'suffix': 'dwi',
                'extension': ['.nii', '.nii.gz'],
                'return_type': 'file',
            }
            if self._session_id:
                query['session'] = self._session_id
            subject_data = {'dwi': sorted(self._layout.get(**query))}
            if not subject_data['dwi']:
                raise KeyError(label)
            records, issues = index_subject(self._layout, subject_data)
            grid = build_policy_grid(records, label, base=self._base_policy, index_issues=issues)
            self._states[label] = (records, issues, grid)
        return self._states[label]

    def page(self, label: str) -> str:
        """The live explorer page for one subject."""
        with self._lock:
            records, issues, grid = self._state(label)
            return render_explorer_html(
                records,
                label,
                index_issues=issues,
                initial_policy=self._base_policy,
                initial_selection=self._initial_selection,
                live_endpoint=f'/sub-{label}/view',
                grid=grid,
            )

    def view(self, label: str, query: str) -> dict:
        """One live view: the query string is the canonical combined key."""
        policy, selection = parse_combined_key(query)
        with self._lock:
            records, issues, grid = self._state(label)
            key = policy.policy_key()
            signature = grid.policy_index.get(key)
            if signature is not None:
                grouping = grid.groupings[signature]
            else:
                # Beyond the embedded grid - the live compiler's whole point.
                grouping = build_for_policy(records, label, policy, issues)
                signature = grouping_signature(grouping)
            resolved = explorer_view(grouping, selection)
        return {
            'policyKey': key,
            'selectionKey': selection.combination_key(),
            'policy': {'sig': signature, 'cli': policy.cli_phrase()},
            **resolved,
        }

    def index_page(self) -> str:
        """The subject list at ``/`` (multi-subject datasets)."""
        items = ''.join(
            f'<li><a href="/sub-{label}">sub-{label}</a></li>' for label in self.subjects
        )
        return (
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            '<title>qsiplan explorer</title></head>\n'
            f'<body><h1>qsiplan explorer</h1><ul>{items}</ul></body></html>'
        )


class _Handler(BaseHTTPRequestHandler):
    app: ExplorerApp  # bound by make_server

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path in ('', '/'):
                if len(self.app.subjects) == 1:
                    self.send_response(302)
                    self.send_header('Location', f'/sub-{self.app.subjects[0]}')
                    self.end_headers()
                    return
                self._send(200, 'text/html', self.app.index_page())
            elif path.startswith('/sub-') and path.endswith('/view'):
                label = path[len('/sub-') : -len('/view')]
                try:
                    # The query is passed verbatim: the canonical key IS the
                    # query string, and it never needs percent-encoding.
                    data = self.app.view(label, parsed.query)
                except ValueError as err:
                    self._send(400, 'application/json', json.dumps({'error': str(err)}))
                    return
                self._send(200, 'application/json', json.dumps(data))
            elif path.startswith('/sub-'):
                self._send(200, 'text/html', self.app.page(path[len('/sub-') :]))
            else:
                self._send(404, 'text/plain', 'not found')
        except KeyError as err:
            self._send(404, 'text/plain', f'no such subject: {err.args[0]}')

    def _send(self, status: int, content_type: str, body: str):
        payload = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', f'{content_type}; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def make_server(app: ExplorerApp, host: str = '127.0.0.1', port: int = 0) -> ThreadingHTTPServer:
    """An HTTP server bound to ``host:port`` (0 picks a free port) for ``app``."""
    handler = type('ExplorerHandler', (_Handler,), {'app': app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def run_server(app: ExplorerApp, host: str = '127.0.0.1', port: int = 8765) -> int:
    """Serve until interrupted; the CLI's ``--serve`` entry point."""
    server = make_server(app, host, port)
    actual_port = server.server_address[1]
    print(f'qsiplan explorer serving at http://{host}:{actual_port}/ (Ctrl+C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped.')
    finally:
        server.server_close()
    return 0
