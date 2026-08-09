#!/usr/bin/env python3
"""
merge_po.py - carry translations from one PO file onto the current upstream file.

Base file provides the structure (occurrences, flags, comments, header, msgids).
The translated file provides msgstr values, matched by (msgctxt, msgid, msgid_plural).
Replacement is text-level: only the msgstr blocks of the base file are swapped, so
the git diff stays limited to the changed translations.

Rules:
  * Exact (msgctxt, msgid, msgid_plural) match with a non-empty translation is applied.
  * Translations whose %-placeholders do not match msgid/msgid_plural are SKIPPED
    (msgfmt would refuse to compile them); the base lines are kept and it is reported.
  * A base '#, fuzzy' flag is cleared when the user's file provides a complete,
    non-fuzzy translation for that msgid.

Usage:
  merge_po.py BASE.po TRANSLATED.po -o OUT.po
"""

import os
import re
import sys

from translate import escape_po, parse_po, read_string_value

_WRAP = 79
_PLURAL_RE = re.compile(r'^msgstr\[(\d+)\]')
_SPECS = re.compile(r'%(?:[0-9]+\$)?[-+ #0]*[0-9]*(?:\.[0-9]+)?[hlL]*(?:[diouxXeEfFgGaAcspn%])')


def _spec_count(s):
    return len(_SPECS.findall(re.sub(r'%%', '', s)))


def _wrap(content, limit):
    if len(content) <= limit:
        return [content]
    words = content.split(' ')
    out = []
    cur = ''
    for w in words:
        if cur == '':
            cur = w
        elif len(cur) + 1 + len(w) <= limit:
            cur += ' ' + w
        else:
            out.append(cur + ' ')
            cur = w
    if cur:
        out.append(cur)
    return out


def render_msgstr_block(prefix, raw):
    """Render a msgstr value as gettext-style wrapped PO lines (prefix + content)."""
    esc = escape_po(raw)
    pieces = esc.split('\\n')
    ends_nl = esc.endswith('\\n')
    contents = [pieces[k] + '\\n' for k in range(len(pieces) - 1)]
    if not ends_nl:
        contents.append(pieces[-1])
    limit_cont = _WRAP - 2
    lines = []
    for c in contents:
        lines.extend(_wrap(c, limit_cont))
    if not lines:
        return [f'{prefix}""']
    if len(lines[0]) + len(prefix) + 2 > _WRAP:
        first, rest = lines[0], lines[1:]
        w1 = _wrap(first, _WRAP - 2 - len(prefix))
        out = [f'{prefix}"{w1[0]}"']
        out += [f'"{p}"' for p in w1[1:]]
        out += [f'"{p}"' for p in rest]
        return out
    out = [f'{prefix}"{lines[0]}"']
    out += [f'"{p}"' for p in lines[1:]]
    return out


def key_of(e):
    return (e.get('msgctxt') or '', e.get('msgid') or '', e.get('msgid_plural') or '')


def _clear_fuzzy(line):
    flags = [f.strip() for f in line[2:].split(',') if f.strip()]
    flags = [f for f in flags if f != 'fuzzy']
    if not flags:
        return None
    return '#, ' + ', '.join(flags)


def merge_text(base_text, user_map):
    lines = base_text.split('\n')
    out = []
    state = {'msgctxt': '', 'msgid': '', 'msgid_plural': '', 'flags': [], 'flag_idx': None}
    stats = {'replaced': 0, 'same': 0, 'empty': 0, 'missing': 0,
             'fuzzy_cleared': 0, 'skipped_format': 0}
    flag_edits = {}
    skipped = []

    def reset_state():
        state['msgctxt'] = ''
        state['msgid'] = ''
        state['msgid_plural'] = ''
        state['flags'] = []
        state['flag_idx'] = None

    def new_val_for(idx):
        user = user_map.get((state['msgctxt'], state['msgid'], state['msgid_plural']))
        if user is None:
            return None
        if idx is None:
            return user.get('msgstr', '')
        return user.get('msgstr_plurals', {}).get(idx, '')

    def guard_ok(new_val, idx):
        if not new_val:
            return True
        if idx is not None:
            expected = _spec_count(state['msgid_plural'])
            return _spec_count(new_val) == expected
        if any(f.endswith('format') for f in state['flags']):
            return _spec_count(new_val) == _spec_count(state['msgid'])
        return True

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        st = line.strip()
        if st == '':
            out.append(line)
            i += 1
            continue
        if st.startswith('#~'):
            out.append(line)
            i += 1
            continue
        if st.startswith('#,'):
            state['flags'] = [f.strip() for f in st[2:].split(',') if f.strip()]
            state['flag_idx'] = len(out)
            out.append(line)
            i += 1
            continue
        if st.startswith('#') or st.startswith('#:') or st.startswith('#.'):
            out.append(line)
            i += 1
            continue
        if st.startswith('msgctxt '):
            val, ni = read_string_value(lines, i)
            state['msgctxt'] = val
            state['msgid_plural'] = ''
            out.extend(lines[i:ni])
            i = ni
            continue
        if st.startswith('msgid '):
            val, ni = read_string_value(lines, i)
            state['msgid'] = val
            state['msgid_plural'] = ''
            out.extend(lines[i:ni])
            i = ni
            continue
        if st.startswith('msgid_plural '):
            val, ni = read_string_value(lines, i)
            state['msgid_plural'] = val
            out.extend(lines[i:ni])
            i = ni
            continue
        m = _PLURAL_RE.match(st)
        if st.startswith('msgstr ') or m:
            if m:
                idx = int(m.group(1))
                if idx != 0:
                    cur_val, ni = read_string_value(lines, i)
                    out.extend(lines[i:ni])
                    i = ni
                    continue
                blocks = []
                j = i
                while True:
                    mm = _PLURAL_RE.match(lines[j].strip())
                    if not mm:
                        break
                    cur_val, nj = read_string_value(lines, j)
                    blocks.append((int(mm.group(1)), cur_val, nj, lines[j:nj]))
                    j = nj
                key = (state['msgctxt'], state['msgid'], state['msgid_plural'])
                user = user_map.get(key)
                user_fuzzy = bool(user and 'fuzzy' in user.get('flags', []))
                applied = True
                user_has = False
                for bidx, _cv, _nj, _blk in blocks:
                    new_val = new_val_for(bidx)
                    if new_val:
                        user_has = True
                        if not guard_ok(new_val, bidx):
                            applied = False
                if not applied:
                    for _bidx, _cv, _nj, blk in blocks:
                        out.extend(blk)
                    skipped.append((key[1], state['msgid_plural']))
                    stats['skipped_format'] += 1
                else:
                    for bidx, cur_val, _nj, _blk in blocks:
                        new_val = new_val_for(bidx)
                        if new_val and new_val != cur_val:
                            out.extend(render_msgstr_block(f'msgstr[{bidx}] ', new_val))
                            stats['replaced'] += 1
                        else:
                            out.extend(_blk)
                            if new_val and new_val == cur_val:
                                stats['same'] += 1
                            elif not cur_val:
                                stats['empty'] += 1
                            else:
                                stats['missing'] += 1
                    if user_has and not user_fuzzy and state['flag_idx'] is not None and 'fuzzy' in state['flags']:
                        flag_edits[state['flag_idx']] = True
                        stats['fuzzy_cleared'] += 1
                i = j
                reset_state()
                continue
            cur_val, ni = read_string_value(lines, i)
            key = (state['msgctxt'], state['msgid'], state['msgid_plural'])
            user = user_map.get(key)
            user_fuzzy = bool(user and 'fuzzy' in user.get('flags', []))
            new_val = new_val_for(None)
            if new_val and not guard_ok(new_val, None):
                out.extend(lines[i:ni])
                skipped.append((key[1], ''))
                stats['skipped_format'] += 1
            else:
                if new_val and new_val != cur_val:
                    out.extend(render_msgstr_block('msgstr ', new_val))
                    stats['replaced'] += 1
                else:
                    out.extend(lines[i:ni])
                    if new_val and new_val == cur_val:
                        stats['same'] += 1
                    elif not cur_val:
                        stats['empty'] += 1
                    else:
                        stats['missing'] += 1
                if new_val and not user_fuzzy and state['flag_idx'] is not None and 'fuzzy' in state['flags']:
                    flag_edits[state['flag_idx']] = True
                    stats['fuzzy_cleared'] += 1
            i = ni
            reset_state()
            continue
        out.append(line)
        i += 1

    if flag_edits:
        deletes = []
        for idx, clear in flag_edits.items():
            if not clear or idx >= len(out):
                continue
            new_line = _clear_fuzzy(out[idx])
            if new_line is None:
                deletes.append(idx)
            else:
                out[idx] = new_line
        for idx in sorted(deletes, reverse=True):
            del out[idx]

    text = '\n'.join(out)
    if base_text.endswith('\n') and not text.endswith('\n'):
        text += '\n'
    return text, stats, skipped


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    base_path = sys.argv[1]
    trans_path = sys.argv[2]
    out_path = None
    if '-o' in sys.argv:
        out_path = sys.argv[sys.argv.index('-o') + 1]

    user_header, user_entries, _ = parse_po(trans_path)
    user_map = {key_of(e): e for e in user_entries}

    base_text = open(base_path, encoding='utf-8').read()
    merged, stats, skipped = merge_text(base_text, user_map)

    _, base_entries, _ = parse_po(base_path)
    base_keys = set()
    for e in base_entries:
        base_keys.add(key_of(e))
    orphans = sorted(set(user_map) - base_keys, key=lambda k: k[1])

    _, out_entries, _ = parse_po_text(merged)
    still_empty = sum(1 for e in out_entries
                      if not e.get('msgstr') and not any(e.get('msgstr_plurals', {}).values()))

    print(f"Base: {len(base_entries)} entries  |  Translated: {len(user_entries)} entries")
    print(f"msgstr replaced: {stats['replaced']}   identical (kept): {stats['same']}")
    print(f"skipped for format mismatch: {stats['skipped_format']}   fuzzy flags cleared: {stats['fuzzy_cleared']}")
    print(f"still untranslated after merge: {still_empty}")
    if skipped:
        print("\nSkipped (translation would not compile; kept base lines):")
        for msgid, plural in skipped:
            print(f"  - {msgid[:80]}")
    if orphans:
        print(f"\nOrphans dropped (removed upstream, {len(orphans)}):")
        for k in orphans:
            print(f"  - {k[1][:80]}")

    if out_path:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(merged)
        print(f"\nWrote {out_path}")


def parse_po_text(text):
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.po')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        return parse_po(path)
    finally:
        os.unlink(path)


if __name__ == '__main__':
    main()
