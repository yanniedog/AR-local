"""Ordinary-user LAN discovery; pinned SSH identity remains the authority."""
from __future__ import annotations

import argparse
import json
import queue
import threading

from laptop_backup_ssh_endpoint import DISCOVERY_NAME, discover_endpoint, lan_ipv4


def resolve_route(fallback: str | None = None, *, timeout: float = 5.0) -> dict[str, str]:
    """Use a configured LAN hint only when name lookup fails or times out."""
    hint = lan_ipv4(fallback) if fallback is not None else None
    result: queue.Queue = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            result.put((discover_endpoint(DISCOVERY_NAME), None))
        except Exception as exc:
            result.put((None, exc))

    # A stuck OS resolver must not keep this short-lived helper process alive.
    threading.Thread(target=lookup, daemon=True).start()
    try:
        address, error = result.get(timeout=timeout)
    except queue.Empty:
        address, error = None, TimeoutError('LAN name lookup timed out')
    if error is None:
        return {'endpoint': lan_ipv4(address), 'source': 'name_lookup'}
    lookup_failure = isinstance(error, TimeoutError) or isinstance(error.__cause__, OSError)
    if hint is not None and lookup_failure:
        return {'endpoint': hint, 'source': 'configured_lan_fallback'}
    # Ambiguous, malformed and non-LAN answers never fall back.
    raise ValueError('LAN discovery failed without an eligible configured fallback') from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fallback')
    args = parser.parse_args()
    try:
        print(json.dumps(resolve_route(args.fallback)))
        return 0
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
