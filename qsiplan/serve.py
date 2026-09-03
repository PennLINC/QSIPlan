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
from collections import OrderedDict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

from .catalog import collect_subject_data
from .explorer import (
    build_for_policy,
    canonical_explorer_policy,
    grouping_signature,
    live_policy_grid,
)
from .interactive import explorer_view, render_explorer_html
from .metadata import index_subject
from .methods import parse_combined_key
from .models import GroupingPolicy


@dataclass
class _SubjectState:
    records: list
    issues: list
    max_policies: int
    groupings: OrderedDict = field(default_factory=OrderedDict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def grouping(self, label, policy):
        key = policy.policy_key()
        with self.lock:
            cached = self.groupings.get(key)
            if cached is not None:
                self.groupings.move_to_end(key)
                return cached
            grouping = build_for_policy(self.records, label, policy, self.issues)
            value = (grouping_signature(grouping), grouping)
            self.groupings[key] = value
            while len(self.groupings) > self.max_policies:
                self.groupings.popitem(last=False)
            return value


class ExplorerApp:
    """The server's request-independent core, kept apart from the HTTP layer.

    Indexes subjects and policies lazily, retains bounded LRU caches, and
    answers view requests with the real compiler. Dataset I/O happens outside
    the global cache lock, while each subject serializes its own policy builds.
    """

    def __init__(
        self,
        source,
        subjects,
        *,
        session_id=None,
        base_policy: GroupingPolicy | None = None,
        initial_selection=None,
        max_cached_subjects: int = 16,
        max_cached_policies: int = 32,
    ):
        self._source = source
        self.subjects = list(subjects)
        self._session_id = session_id
        self._base_policy = canonical_explorer_policy(base_policy)
        self._initial_selection = initial_selection
        self._max_cached_subjects = max(1, max_cached_subjects)
        self._max_cached_policies = max(1, max_cached_policies)
        self._lock = threading.Lock()
        self._states = OrderedDict()
        self._index_lock = threading.Lock()
        self._index_html = None

    def _state(self, label):
        """A bounded, lazily indexed state for one subject."""
        if label not in self.subjects:
            raise KeyError(label)
        with self._lock:
            state = self._states.get(label)
            if state is not None:
                self._states.move_to_end(label)
                return state

        # Dataset I/O and grouping happen outside the global cache lock, so a
        # large first request does not block already-indexed subjects.
        subject_data = collect_subject_data(self._source, label, self._session_id)
        if not subject_data['dwi']:
            raise KeyError(label)
        records, issues = index_subject(self._source, subject_data)
        state = _SubjectState(records, issues, self._max_cached_policies)
        with self._lock:
            state = self._states.setdefault(label, state)
            self._states.move_to_end(label)
            while len(self._states) > self._max_cached_subjects:
                self._states.popitem(last=False)
        return state

    def page(self, label: str) -> str:
        """The live explorer page for one subject."""
        state = self._state(label)
        _signature, grouping = state.grouping(label, self._base_policy)
        grid = live_policy_grid(grouping, self._base_policy)
        return render_explorer_html(
            state.records,
            label,
            index_issues=state.issues,
            initial_policy=self._base_policy,
            initial_selection=self._initial_selection,
            live_endpoint=f'/sub-{label}/view',
            grid=grid,
        )

    def view(self, label: str, query: str) -> dict:
        """One live view: the query string is the canonical combined key."""
        policy, selection = parse_combined_key(query)
        state = self._state(label)
        key = policy.policy_key()
        signature, grouping = state.grouping(label, policy)
        resolved = explorer_view(grouping, selection)
        return {
            'policyKey': key,
            'selectionKey': selection.combination_key(),
            'policy': {'sig': signature, 'cli': policy.cli_phrase()},
            **resolved,
        }

    def index_page(self) -> str:
        """The cohort dashboard at ``/`` - the group-level view over all subjects.

        Built once (indexing every subject and compiling each method's plan) and
        cached; subsequent hits are instant. Each subject/class drills into its
        live ``/sub-<label>`` explorer.
        """
        with self._index_lock:
            if self._index_html is None:
                from .cohort import render_cohort_html

                initial_method = (
                    self._initial_selection.hmc.value
                    if self._initial_selection is not None
                    else None
                )
                self._index_html = render_cohort_html(
                    self._source,
                    self.subjects,
                    session_id=self._session_id,
                    policy=self._base_policy,
                    live=True,
                    initial_method=initial_method,
                )
            return self._index_html


class _Handler(BaseHTTPRequestHandler):
    app: ExplorerApp  # bound by make_server

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path in ('', '/'):
                if len(self.app.subjects) == 1:
                    self.send_response(302)
                    self.send_header('Location', f'/sub-{quote(self.app.subjects[0], safe="")}')
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
