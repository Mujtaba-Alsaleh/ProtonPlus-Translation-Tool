#!/usr/bin/env python3
"""
ProtonPlus Translator - Local PO translation tool (GTK4)
"""

import os
import sys
import re
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from difflib import SequenceMatcher


# ── PO Parser ─────────────────────────────────────────────────────────────────

def parse_string_line(line):
    s = line.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return None


def unescape_po(s):
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            if c == 'n': result.append('\n')
            elif c == 't': result.append('\t')
            elif c == '"': result.append('"')
            elif c == '\\': result.append('\\')
            else: result.append(s[i:i+2])
            i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def escape_po(s):
    return (s.replace('\\', '\\\\').replace('"', '\\"')
             .replace('\n', '\\n').replace('\t', '\\t'))


def read_string_value(lines, start_idx):
    raw = ''
    idx = start_idx
    first = True
    while idx < len(lines):
        s = lines[idx].strip()
        if first:
            first = False
            m = re.match(r'^msgstr\[(\d+)\]\s*"(.*)"$', s)
            if m:
                raw += m.group(2)
                idx += 1
                continue
            for prefix in ['msgctxt ', 'msgid_plural ', 'msgid ', 'msgstr ']:
                if s.startswith(prefix):
                    rest = s[len(prefix):]
                    extracted = parse_string_line(rest)
                    if extracted is not None:
                        raw += extracted
                        idx += 1
                        break
            else:
                break
        else:
            extracted = parse_string_line(s)
            if extracted is not None:
                raw += extracted
                idx += 1
            else:
                break
    return unescape_po(raw), idx


def parse_po(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')

    header = {'comment': '', 'tcomment': '', 'flags': [], 'occurrences': [],
              'msgctxt': '', 'msgid': '', 'msgstr': ''}
    entries = []
    current = None

    def new_entry():
        return {'pre_lines': [], 'comment': '', 'tcomment': '', 'flags': [],
                'occurrences': [], 'msgctxt': '', 'msgid': '', 'msgid_plural': '',
                'msgstr': '', 'msgstr_plurals': {}}

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == '' or stripped.startswith('#~'):
            i += 1; continue

        if stripped.startswith('#:'):
            if current is not None and (current['msgid'] or current['msgstr']):
                entries.append(current)
            current = new_entry()
            occ_text = stripped[2:].strip()
            current['occurrences'] = [o.strip() for o in occ_text.split() if o.strip()]
            i += 1; continue

        if stripped.startswith('#,'):
            flags_text = stripped[2:].strip()
            target = current if current is not None else header
            target['flags'] = [f.strip() for f in flags_text.split(',') if f.strip()]
            i += 1; continue

        if stripped.startswith('#.'):
            comment_text = stripped[2:]
            target = current if current is not None else header
            target['comment'] = (target['comment'] + '\n' + comment_text).strip('\n')
            i += 1; continue

        if stripped.startswith('#'):
            comment_text = stripped[1:].strip() if len(stripped) > 1 else ''
            target = current if current is not None else header
            target['tcomment'] = (target['tcomment'] + '\n' + comment_text).strip('\n')
            i += 1; continue

        if stripped.startswith('msgctxt '):
            if current is None: current = new_entry()
            current['msgctxt'], i = read_string_value(lines, i)
            continue

        if stripped.startswith('msgid_plural '):
            if current is None: current = new_entry()
            current['msgid_plural'], i = read_string_value(lines, i)
            continue

        if stripped.startswith('msgid '):
            if current is not None and current['msgid']:
                entries.append(current)
            if current is None:
                current = new_entry()
            current['msgid'], i = read_string_value(lines, i)
            continue

        m = re.match(r'^msgstr\[(\d+)\]\s', stripped)
        if m:
            if current is None: current = new_entry()
            idx = int(m.group(1))
            val, i = read_string_value(lines, i)
            current['msgstr_plurals'][idx] = val
            if len(current['msgstr_plurals']) == 1:
                current['msgstr'] = val
            continue

        if stripped.startswith('msgstr '):
            if current is None: current = new_entry()
            current['msgstr'], i = read_string_value(lines, i)
            continue

        i += 1

    if current is not None and (current['msgid'] or current['msgstr'] or current['flags']):
        entries.append(current)

    if entries and entries[0]['msgid'] == '' and not entries[0]['flags']:
        header_entry = entries.pop(0)
        header['msgstr'] = header_entry['msgstr']
        if header_entry['comment']: header['comment'] = header_entry['comment']
        if header_entry['tcomment']: header['tcomment'] = header_entry['tcomment']

    return header, entries


def status_of(entry):
    if 'fuzzy' in entry.get('flags', []): return 'fuzzy'
    if entry.get('msgstr', ''): return 'translated'
    return 'untranslated'


def build_translation_memory(entries):
    memory = {}
    for e in entries:
        if status_of(e) == 'translated' and e.get('msgid'):
            memory[e['msgid']] = e['msgstr']
    return memory


def write_po(filepath, header, entries):
    out = []
    out.append('# SOME DESCRIPTIVE TITLE.')
    out.append('# Copyright (C) YEAR THE PACKAGE\'S COPYRIGHT HOLDER')
    out.append('# This file is distributed under the same license as the com.vysp3r.ProtonPlus package.')
    if header.get('tcomment'):
        for line in header['tcomment'].split('\n'):
            if line.strip(): out.append(f'# {line}')
    if header.get('comment'):
        for line in header['comment'].split('\n'):
            if line.strip(): out.append(f'#. {line}')
    if header.get('flags'):
        out.append('#, ' + ', '.join(header['flags']))
    out.append('msgid ""')
    ms = escape_po(header.get('msgstr', ''))
    ms_parts = ms.split('\\n')
    for pi, part in enumerate(ms_parts):
        chunk = part + '\\n' if pi < len(ms_parts) - 1 else part
        prefix = 'msgstr ' if pi == 0 else ''
        out.append(f'{prefix}"{chunk}"')

    for entry in entries:
        out.append('')
        for occ in entry.get('occurrences', []):
            out.append(f'#: {occ}')
        if entry.get('flags'):
            out.append('#, ' + ', '.join(entry['flags']))
        if entry.get('comment', '').strip():
            for cl in entry['comment'].strip().split('\n'):
                out.append(f'#. {cl.strip()}')
        if entry.get('tcomment', '').strip():
            for cl in entry['tcomment'].strip().split('\n'):
                if cl.strip(): out.append(f'# {cl.strip()}')

        if entry.get('msgctxt'):
            ec = escape_po(entry['msgctxt']).split('\\n')
            for pi, part in enumerate(ec):
                chunk = part + '\\n' if pi < len(ec) - 1 else part
                out.append(f'{"msgctxt " if pi == 0 else ""}"{chunk}"')

        em = escape_po(entry['msgid']).split('\\n')
        for pi, part in enumerate(em):
            chunk = part + '\\n' if pi < len(em) - 1 else part
            out.append(f'{"msgid " if pi == 0 else ""}"{chunk}"')

        if entry.get('msgid_plural'):
            ep = escape_po(entry['msgid_plural']).split('\\n')
            for pi, part in enumerate(ep):
                chunk = part + '\\n' if pi < len(ep) - 1 else part
                out.append(f'{"msgid_plural " if pi == 0 else ""}"{chunk}"')
            for idx in sorted(entry.get('msgstr_plurals', {}).keys()):
                ev = escape_po(entry['msgstr_plurals'][idx]).split('\\n')
                for pi, part in enumerate(ev):
                    chunk = part + '\\n' if pi < len(ev) - 1 else part
                    out.append(f'{"msgstr[" + str(idx) + "] " if pi == 0 else ""}"{chunk}"')
        else:
            ems = escape_po(entry.get('msgstr', '')).split('\\n')
            for pi, part in enumerate(ems):
                chunk = part + '\\n' if pi < len(ems) - 1 else part
                out.append(f'{"msgstr " if pi == 0 else ""}"{chunk}"')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
        if out and not out[-1].endswith('\n'):
            f.write('\n')


def find_similar(msgid, memory, top_n=8):
    if not msgid: return []
    results = []
    msgid_lower = msgid.lower()
    msgid_words = set(re.findall(r'\w+', msgid_lower))
    for source, translation in memory.items():
        if source == msgid: continue
        source_lower = source.lower()
        ratio = SequenceMatcher(None, msgid_lower, source_lower).ratio()
        source_words = set(re.findall(r'\w+', source_lower))
        common = msgid_words & source_words
        word_score = len(common) / max(len(msgid_words), 1)
        score = max(ratio, word_score * 0.9)
        if score > 0.18:
            results.append((score, source, translation))
    results.sort(key=lambda x: -x[0])
    return results[:top_n]


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = b"""
window, headerbar {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
.title {
    font-size: 16px;
    font-weight: bold;
    color: #cdd6f4;
}
.subtitle {
    font-size: 11px;
    color: #a6adc8;
}
.source-label {
    font-size: 11px;
    font-weight: bold;
    color: #a6adc8;
}
.source-text {
    font-family: monospace;
    font-size: 13px;
    color: #cdd6f4;
    background-color: #181825;
    padding: 10px;
    border-radius: 8px;
}
.translation-text {
    font-family: monospace;
    font-size: 13px;
    color: #cdd6f4;
    background-color: #181825;
    padding: 10px;
    border-radius: 8px;
}
.translation-text:focus {
    border-color: #a6e3a1;
}
.btn {
    padding: 6px 16px;
    border-radius: 6px;
    font-size: 12px;
}
.btn-accent {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
.btn-accent:hover {
    background-color: #b4d0fb;
}
.btn-save {
    background-color: #a6e3a1;
    color: #1e1e2e;
}
.btn-discard {
    background-color: #f38ba8;
    color: #1e1e2e;
}
.fuzzy-badge {
    background-color: #f9e2af;
    color: #1e1e2e;
    font-size: 10px;
    font-weight: bold;
    padding: 2px 8px;
    border-radius: 4px;
}
.list-item {
    padding: 6px 10px;
    font-size: 12px;
    color: #cdd6f4;
}
.list-item:selected {
    background-color: #313244;
    color: #89b4fa;
}
.list-item:hover {
    background-color: #313244;
}
.rec-source {
    font-size: 11px;
    color: #89b4fa;
    padding: 2px 8px;
}
.rec-target {
    font-size: 12px;
    color: #a6e3a1;
    padding: 2px 12px;
}
.rec-score {
    font-size: 10px;
    color: #a6adc8;
}
.count-ut { color: #f38ba8; font-size: 11px; }
.count-fz { color: #f9e2af; font-size: 11px; }
.count-tr { color: #a6e3a1; font-size: 11px; }
.status-bar {
    background-color: #181825;
    color: #a6adc8;
    font-size: 11px;
    padding: 4px 10px;
}
filter radio {
    color: #cdd6f4;
}
filter radio:selected {
    color: #89b4fa;
}
scrolledwindow {
    background-color: #181825;
}
search {
    background-color: #181825;
    color: #cdd6f4;
}
"""


# ── GTK Application ──────────────────────────────────────────────────────────

class TranslatorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, filepath=None):
        super().__init__(application=app, title="ProtonPlus Translator")
        self.set_default_size(1300, 840)

        self.filepath = None
        self.header = {}
        self.entries = []
        self.filtered = []
        self.current_index = 0
        self.modified = False
        self.memory = {}
        self.current_filter = "all"
        self.search_text = ""
        self._suppress_select = False

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(vbox)

        self._build_header_bar()
        vbox.append(self._build_top_bar())

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        vbox.append(paned)

        paned.set_start_child(self._build_left())
        paned.set_end_child(self._build_right())

        self._build_status_bar(vbox)

        if filepath:
            self._load_file(filepath)

    def _build_header_bar(self):
        hb = Gtk.HeaderBar()
        self.set_titlebar(hb)

        menu = Gtk.MenuButton()
        menu.set_icon_name("open-menu-symbolic")
        pop = Gtk.Popover()
        mb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mb.set_margin_top(8)
        mb.set_margin_bottom(8)
        mb.set_margin_start(8)
        mb.set_margin_end(8)

        btn_open = Gtk.Button(label="Open PO File...")
        btn_open.add_css_class("btn")
        btn_open.connect("clicked", lambda b: self._open_file())
        mb.append(btn_open)

        btn_tm = Gtk.Button(label="Import Translation Memory...")
        btn_tm.add_css_class("btn")
        btn_tm.connect("clicked", lambda b: self._open_tm())
        mb.append(btn_tm)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        mb.append(sep)

        btn_save = Gtk.Button(label="Save")
        btn_save.add_css_class("btn")
        btn_save.add_css_class("btn-save")
        btn_save.connect("clicked", lambda b: self._save_file())
        mb.append(btn_save)

        btn_save_as = Gtk.Button(label="Save As...")
        btn_save_as.add_css_class("btn")
        btn_save_as.connect("clicked", lambda b: self._save_as())
        mb.append(btn_save_as)

        pop.set_child(mb)
        menu.set_popover(pop)
        hb.pack_end(menu)

    def _build_top_bar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(4)

        lbl = Gtk.Label(label="ProtonPlus Translator")
        lbl.add_css_class("title")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        box.append(lbl)

        self.lbl_file = Gtk.Label(label="No file loaded")
        self.lbl_file.add_css_class("subtitle")
        self.lbl_file.set_halign(Gtk.Align.END)
        box.append(self.lbl_file)

        return box

    def _build_left(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(8)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(8)
        box.set_size_request(350, -1)

        self.filter_var = "all"
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.filter_buttons = {}
        for label, val in [("All", "all"), ("Untranslated", "untranslated"),
                            ("Translated", "translated"), ("Fuzzy", "fuzzy")]:
            rb = Gtk.ToggleButton(label=label)
            rb.add_css_class("btn")
            if val == "all":
                rb.set_active(True)
            rb.connect("toggled", self._on_filter_toggled, val)
            self.filter_buttons[val] = rb
            filter_box.append(rb)
        box.append(filter_box)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search source or translation...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        box.append(self.search_entry)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)

        scroll.set_child(self.listbox)
        box.append(scroll)

        count_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        count_box.set_margin_top(4)
        self.lbl_ut = Gtk.Label(label="0 untranslated")
        self.lbl_ut.add_css_class("count-ut")
        count_box.append(self.lbl_ut)
        self.lbl_fz = Gtk.Label(label="0 fuzzy")
        self.lbl_fz.add_css_class("count-fz")
        count_box.append(self.lbl_fz)
        self.lbl_tr = Gtk.Label(label="0 translated")
        self.lbl_tr.add_css_class("count-tr")
        count_box.append(self.lbl_tr)
        box.append(count_box)

        return box

    def _build_right(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(4)
        box.set_margin_end(8)
        box.set_margin_top(4)
        box.set_margin_bottom(8)

        lbl = Gtk.Label(label="SOURCE STRING")
        lbl.add_css_class("source-label")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self.txt_source = Gtk.TextView()
        self.txt_source.set_editable(False)
        self.txt_source.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.txt_source.set_left_margin(10)
        self.txt_source.set_right_margin(10)
        self.txt_source.set_top_margin(8)
        self.txt_source.set_bottom_margin(8)
        self.txt_source.add_css_class("source-text")
        self.txt_source.set_size_request(-1, 80)
        box.append(self.txt_source)

        h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl2 = Gtk.Label(label="YOUR TRANSLATION")
        lbl2.add_css_class("source-label")
        lbl2.set_halign(Gtk.Align.START)
        lbl2.set_hexpand(True)
        h_box.append(lbl2)
        self.fuzzy_badge = Gtk.Label(label="FUZZY")
        self.fuzzy_badge.add_css_class("fuzzy-badge")
        self.fuzzy_badge.set_visible(False)
        h_box.append(self.fuzzy_badge)
        box.append(h_box)

        scroll_edit = Gtk.ScrolledWindow()
        scroll_edit.set_size_request(-1, 100)
        scroll_edit.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.txt_translation = Gtk.TextView()
        self.txt_translation.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.txt_translation.set_left_margin(10)
        self.txt_translation.set_right_margin(10)
        self.txt_translation.set_top_margin(8)
        self.txt_translation.set_bottom_margin(8)
        self.txt_translation.add_css_class("translation-text")
        self.txt_translation.get_buffer().connect("changed", self._on_translation_changed)
        scroll_edit.set_child(self.txt_translation)
        box.append(scroll_edit)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        btn_back = Gtk.Button(label="Back")
        btn_back.add_css_class("btn")
        btn_back.connect("clicked", lambda b: self._prev())
        nav_box.append(btn_back)

        btn_save_next = Gtk.Button(label="Save & Next")
        btn_save_next.add_css_class("btn")
        btn_save_next.add_css_class("btn-accent")
        btn_save_next.connect("clicked", lambda b: self._save_next())
        nav_box.append(btn_save_next)

        btn_save = Gtk.Button(label="Save")
        btn_save.add_css_class("btn")
        btn_save.add_css_class("btn-save")
        btn_save.connect("clicked", lambda b: self._save_file())
        nav_box.append(btn_save)

        btn_discard = Gtk.Button(label="Discard")
        btn_discard.add_css_class("btn")
        btn_discard.add_css_class("btn-discard")
        btn_discard.connect("clicked", lambda b: self._discard())
        nav_box.append(btn_discard)

        btn_next = Gtk.Button(label="Next")
        btn_next.add_css_class("btn")
        btn_next.connect("clicked", lambda b: self._next())
        nav_box.append(btn_next)

        nav_box.append(Gtk.Label())  # spacer

        btn_fuzzy = Gtk.Button(label="Toggle Fuzzy")
        btn_fuzzy.add_css_class("btn")
        btn_fuzzy.connect("clicked", lambda b: self._toggle_fuzzy())
        nav_box.append(btn_fuzzy)

        box.append(nav_box)

        lbl3 = Gtk.Label(label="TRANSLATION MEMORY SUGGESTIONS")
        lbl3.add_css_class("source-label")
        lbl3.set_halign(Gtk.Align.START)
        box.append(lbl3)

        rec_scroll = Gtk.ScrolledWindow()
        rec_scroll.set_vexpand(True)
        rec_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.rec_listbox = Gtk.ListBox()
        self.rec_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.rec_listbox.connect("row-activated", self._on_rec_activated)
        rec_scroll.set_child(self.rec_listbox)
        box.append(rec_scroll)

        return box

    def _build_status_bar(self, parent):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("status-bar")
        bar.set_margin_top(4)
        self.lbl_status = Gtk.Label(label="Ready")
        self.lbl_status.set_halign(Gtk.Align.START)
        self.lbl_status.set_hexpand(True)
        bar.append(self.lbl_status)
        self.lbl_counts = Gtk.Label(label="")
        self.lbl_counts.set_halign(Gtk.Align.END)
        bar.append(self.lbl_counts)
        parent.append(bar)

    # ── File Operations ──

    def _open_file(self):
        dlg = Gtk.FileDialog()
        f = Gtk.FileFilter()
        f.set_name("PO files")
        f.add_pattern("*.po")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        f2 = Gtk.FileFilter()
        f2.set_name("All files")
        f2.add_pattern("*")
        filters.append(f2)
        dlg.set_filters(filters)
        dlg.open(self, None, self._on_file_opened)

    def _on_file_opened(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        if gfile:
            self._load_file(gfile.get_path())

    def _open_tm(self):
        dlg = Gtk.FileDialog()
        f = Gtk.FileFilter()
        f.set_name("PO files")
        f.add_pattern("*.po")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg.set_filters(filters)
        dlg.open(self, None, self._on_tm_opened)

    def _on_tm_opened(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        if gfile:
            self._load_tm(gfile.get_path())

    def _load_file(self, path):
        try:
            header, entries = parse_po(path)
        except Exception as e:
            dlg = Gtk.AlertDialog()
            dlg.set_message(f"Failed to parse PO file:\n{e}")
            dlg.show(self)
            return
        self.filepath = path
        self.header = header
        self.entries = entries
        self.modified = False
        self.memory = build_translation_memory(entries)
        self._rebuild_filtered()
        self.current_index = 0
        self._rebuild_listbox()
        self._update_counts()
        self.lbl_file.set_text(os.path.basename(path))
        self.set_title(f"ProtonPlus Translator - {os.path.basename(path)}")
        self.lbl_status.set_text(f"Loaded {len(entries)} entries")

    def _load_tm(self, path):
        try:
            _, entries = parse_po(path)
        except Exception as e:
            dlg = Gtk.AlertDialog()
            dlg.set_message(f"Failed to parse:\n{e}")
            dlg.show(self)
            return
        old = build_translation_memory(entries)
        self.memory.update(old)
        dlg = Gtk.AlertDialog()
        dlg.set_message(f"Loaded {len(old)} translations.\nTotal TM: {len(self.memory)} entries.")
        dlg.set_detail("Translation Memory Imported")
        dlg.show(self)

    def _save_file(self, rebuild=True):
        if not self.filepath:
            return
        self._apply_current()
        try:
            write_po(self.filepath, self.header, self.entries)
            self.modified = False
            self.lbl_status.set_text("Saved!")
            self._update_counts()
            if rebuild:
                self._refresh()
        except Exception as e:
            dlg = Gtk.AlertDialog()
            dlg.set_message(f"Failed to save:\n{e}")
            dlg.show(self)

    def _save_next(self):
        self._apply_current()
        if not self.filepath:
            return
        try:
            write_po(self.filepath, self.header, self.entries)
            self.modified = False
            self._update_counts()
        except Exception as e:
            dlg = Gtk.AlertDialog()
            dlg.set_message(f"Failed to save:\n{e}")
            dlg.show(self)
            return
        saved_index = self.current_index
        self._rebuild_filtered()
        self.current_index = min(len(self.filtered) - 1, saved_index + 1)
        self._rebuild_listbox()
        self._update_nav_label()

    def _save_as(self):
        dlg = Gtk.FileDialog()
        dlg.set_title("Save As")
        f = Gtk.FileFilter()
        f.set_name("PO files")
        f.add_pattern("*.po")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg.set_filters(filters)
        dlg.save(self, None, self._on_save_as)

    def _on_save_as(self, dialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return
        if gfile:
            old = self.filepath
            self.filepath = gfile.get_path()
            self._save_file()
            if old:
                self.filepath = old

    # ── Filter & List ──

    def _on_filter_toggled(self, button, value):
        if button.get_active():
            self.filter_var = value
            self._refresh()

    def _on_search_changed(self, entry):
        self.search_text = entry.get_text().strip().lower()
        self._refresh()

    def _rebuild_filtered(self):
        self.filtered = []
        for e in self.entries:
            st = status_of(e)
            if self.filter_var != "all" and st != self.filter_var:
                continue
            if self.search_text:
                if (self.search_text in e.get('msgid', '').lower()
                        or self.search_text in e.get('msgstr', '').lower()):
                    self.filtered.append(e)
            else:
                self.filtered.append(e)

    def _refresh(self):
        self._apply_current()
        self._rebuild_filtered()
        self.current_index = min(self.current_index, max(0, len(self.filtered) - 1))
        self._rebuild_listbox()
        self._update_nav_label()

    def _rebuild_listbox(self):
        self._suppress_select = True
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        for entry in self.filtered:
            row = self._make_list_row(entry)
            self.listbox.append(row)
        self._suppress_select = False
        if self.filtered:
            self._show_entry(self.filtered[self.current_index])
            self._highlight_current_row()

    def _make_list_row(self, entry):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        st = status_of(entry)
        sym = {"translated": "\u2713", "fuzzy": "?", "untranslated": "\u25cb"}
        lbl = Gtk.Label(label=sym.get(st, ""))
        lbl.set_size_request(20, -1)
        if st == "translated":
            lbl.add_css_class("count-tr")
        elif st == "fuzzy":
            lbl.add_css_class("count-fz")
        else:
            lbl.add_css_class("count-ut")
        box.append(lbl)

        msgid = entry.get('msgid', '')
        display = msgid if len(msgid) <= 80 else msgid[:77] + "..."
        lbl2 = Gtk.Label(label=display)
        lbl2.set_halign(Gtk.Align.START)
        lbl2.set_ellipsize(Pango.EllipsizeMode.END)
        lbl2.set_xalign(0)
        box.append(lbl2)

        row = Gtk.ListBoxRow()
        row.set_child(box)
        row.entry = entry
        row.set_tooltip_text(msgid[:200])
        return row

    def _on_row_selected(self, listbox, row):
        if self._suppress_select or row is None:
            return
        entry = row.entry
        self._apply_current()
        if entry in self.filtered:
            self.current_index = self.filtered.index(entry)
        self._show_entry(entry)

    def _show_entry(self, entry):
        self._suppress_select = True
        buf = self.txt_source.get_buffer()
        buf.set_text(entry.get('msgctxt', ''))
        if entry.get('msgctxt'):
            buf.insert(buf.get_end_iter(), '\n')
        buf.insert(buf.get_end_iter(), entry.get('msgid', ''))

        ebuf = self.txt_translation.get_buffer()
        ebuf.set_text(entry.get('msgstr', ''))

        self.fuzzy_badge.set_visible('fuzzy' in entry.get('flags', []))
        self._update_recommendations(entry)
        self._update_nav_label()
        self._suppress_select = False

    def _update_recommendations(self, entry):
        children = []
        child = self.rec_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            children.append(child)
            child = nxt
        for c in children:
            self.rec_listbox.remove(c)

        sims = find_similar(entry.get('msgid', ''), self.memory)
        if not sims:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="  No similar translations found in memory.")
            lbl.set_halign(Gtk.Align.START)
            lbl.add_css_class("subtitle")
            row.set_child(lbl)
            self.rec_listbox.append(row)
            return

        for score, source, translation in sims:
            pct = int(score * 100)
            ss = source if len(source) <= 60 else source[:57] + "..."
            st = translation if len(translation) <= 60 else translation[:57] + "..."

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            box.set_margin_start(8)
            box.set_margin_end(8)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            score_lbl = Gtk.Label(label=f"[{pct}%]")
            score_lbl.add_css_class("rec-score")
            score_lbl.set_halign(Gtk.Align.START)
            top.append(score_lbl)
            src_lbl = Gtk.Label(label=ss)
            src_lbl.add_css_class("rec-source")
            src_lbl.set_halign(Gtk.Align.START)
            src_lbl.set_hexpand(True)
            src_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            top.append(src_lbl)
            box.append(top)

            tgt_lbl = Gtk.Label(label=f"→ {st}")
            tgt_lbl.add_css_class("rec-target")
            tgt_lbl.set_halign(Gtk.Align.START)
            tgt_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(tgt_lbl)

            row = Gtk.ListBoxRow()
            row.set_child(box)
            row.rec_translation = translation
            self.rec_listbox.append(row)

    def _on_rec_activated(self, listbox, row):
        if row and hasattr(row, 'rec_translation'):
            ebuf = self.txt_translation.get_buffer()
            ebuf.set_text(row.rec_translation)

    def _update_nav_label(self):
        total = len(self.filtered)
        if total == 0:
            self.lbl_status.set_text("No entries in current filter")
            return
        entry = self.filtered[self.current_index] if self.current_index < len(self.filtered) else None
        if entry:
            self.lbl_status.set_text(f"{self.current_index + 1}/{total} [{status_of(entry).upper()}]")

    def _update_counts(self):
        ut = sum(1 for e in self.entries if status_of(e) == "untranslated")
        fz = sum(1 for e in self.entries if status_of(e) == "fuzzy")
        tr = sum(1 for e in self.entries if status_of(e) == "translated")
        total = max(len(self.entries), 1)
        self.lbl_ut.set_text(f"{ut} untranslated")
        self.lbl_fz.set_text(f"{fz} fuzzy")
        self.lbl_tr.set_text(f"{tr} translated")
        self.lbl_counts.set_text(f"{tr}/{total} translated ({100*tr//total}%)")

    # ── Navigation ──

    def _apply_current(self):
        if self.current_index >= len(self.filtered):
            return
        entry = self.filtered[self.current_index]
        ebuf = self.txt_translation.get_buffer()
        start = ebuf.get_start_iter()
        end = ebuf.get_end_iter()
        new_val = ebuf.get_text(start, end, True)
        entry['msgstr'] = new_val
        if new_val and 'fuzzy' in entry.get('flags', []):
            entry['flags'].remove('fuzzy')
        if new_val:
            self.memory[entry['msgid']] = new_val
        self.modified = True


    def _find_row_for_entry(self, entry):
        child = self.listbox.get_first_child()
        while child is not None:
            if hasattr(child, 'entry') and child.entry is entry:
                return child
            child = child.get_next_sibling()
        return None

    def _highlight_current_row(self):
        if not self.filtered:
            return
        entry = self.filtered[min(self.current_index, len(self.filtered) - 1)]
        row = self._find_row_for_entry(entry)
        if row:
            self._suppress_select = True
            self.listbox.select_row(row)
            self._suppress_select = False

    def _prev(self):
        if not self.filtered: return
        self._apply_current()
        self.current_index = max(0, self.current_index - 1)
        self._show_entry(self.filtered[self.current_index])
        self._update_nav_label()
        self._highlight_current_row()

    def _next(self):
        if not self.filtered: return
        self._apply_current()
        self.current_index = min(len(self.filtered) - 1, self.current_index + 1)
        self._show_entry(self.filtered[self.current_index])
        self._update_nav_label()
        self._highlight_current_row()

    def _discard(self):
        if self.current_index < len(self.filtered):
            entry = self.filtered[self.current_index]
            ebuf = self.txt_translation.get_buffer()
            ebuf.set_text(entry.get('msgstr', ''))
            self.modified = False
            self.lbl_status.set_text("Discarded")

    def _clear_translation(self):
        ebuf = self.txt_translation.get_buffer()
        ebuf.set_text("")

    def _copy_source(self):
        if self.current_index < len(self.filtered):
            entry = self.filtered[self.current_index]
            ebuf = self.txt_translation.get_buffer()
            ebuf.set_text(entry.get('msgid', ''))

    def _toggle_fuzzy(self):
        if self.current_index >= len(self.filtered):
            return
        entry = self.filtered[self.current_index]
        flags = entry.get('flags', [])
        if 'fuzzy' in flags:
            flags.remove('fuzzy')
            self.fuzzy_badge.set_visible(False)
        else:
            flags.append('fuzzy')
            self.fuzzy_badge.set_visible(True)
        entry['flags'] = flags
        self.modified = True

    def _on_translation_changed(self, buf):
        self.modified = True


# ── Main ──────────────────────────────────────────────────────────────────────

from gi.repository import Gio


class TranslatorApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.protonplus.translator.gui",
                         flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)

    def _on_activate(self, app):
        win = TranslatorWindow(app)
        win.present()

    def _on_open(self, app, files, n_files, hints):
        win = TranslatorWindow(app, filepath=files[0].get_path())
        win.present()


def main():
    css = Gtk.CssProvider()
    css.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    app = TranslatorApp()
    if len(sys.argv) > 1:
        app.run([sys.argv[0], sys.argv[1]])
    else:
        app.run(sys.argv)


if __name__ == "__main__":
    main()
