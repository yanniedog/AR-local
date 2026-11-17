"""Authenticated full pagination for evidence-bearing alias upload planning.

No deletions. A failed/ambiguous enumeration is never treated as an empty set.
"""
import json
import re

from app_payload_revisions_state import RevisionError


def list_asset_names(gh, repo, tag, *, runner):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not re.fullmatch(r'[A-Za-z0-9_.-]+', tag):
        raise RevisionError('invalid release listing target')
    def request(arguments):
        result = runner([gh, 'api', *arguments], capture_output=True, text=True, timeout=300)
        if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
            raise RevisionError('complete authenticated asset listing failed')
        try: return json.loads(result.stdout)
        except (ValueError, RecursionError): raise RevisionError('invalid complete asset listing') from None
    release = request([f'repos/{repo}/releases/tags/{tag}'])
    if (not isinstance(release, dict) or release.get('tag_name') != tag
            or type(release.get('id')) is not int or release['id'] <= 0):
        raise RevisionError('release listing identity differs')
    # gh follows every server Link header; --slurp retains page boundaries.
    pages = request(['--paginate', '--slurp', f"repos/{repo}/releases/{release['id']}/assets?per_page=100"])
    if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
        raise RevisionError('invalid asset pagination')
    names = set(); identities = set()
    for page in pages:
        if not isinstance(page, list) or len(page) > 100:
            raise RevisionError('invalid asset page')
        for asset in page:
            if (not isinstance(asset, dict) or type(asset.get('id')) is not int or asset['id'] <= 0
                    or not isinstance(asset.get('name'), str) or not asset['name'] or len(asset['name']) > 255
                    or asset['name'] in names or asset['id'] in identities):
                raise RevisionError('ambiguous release asset listing')
            names.add(asset['name']); identities.add(asset['id'])
    return names
