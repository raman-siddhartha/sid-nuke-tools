# Connect node v3 for Nuke 16.
# Save as connect_node.py in your ~/.nuke folder and add the menu lines to menu.py.
# Or paste into the Script Editor to open the Connect popup.
import nuke

# Live label on the node in the DAG. Falls back to "nothing" when disconnected.
LABEL = "Connected to [if {[catch {value input0.name} r]} {set r nothing}; set r]"

CONNECT_COLOR = 0x1fb8c800   # teal, connected
DUMMY_COLOR = 0xf0901800     # orange, connected dummy
BROKEN_COLOR = 0xFF000000    # red, not connected
LABEL_SIZE = 20

# Walks Connect and dummy nodes to the real source. Returns (text, ok).
# ok is False when nothing is connected or a dummy in the chain leads nowhere.
# Kept as one self-contained function so it also works inside node callbacks.
DESCRIBE = """
def describe(node):
    via = []
    src = node.input(0)
    while src is not None and 'connectNode' in src.knobs():
        nxt = src.input(0)
        if nxt is None or len(via) >= 20:
            return 'Nothing (' + src.name() + ' is not connected)', False
        via.append(src.name())
        src = nxt
    if src is None:
        return 'Nothing', False
    if via:
        return src.name() + ' (via ' + ' > '.join(via) + ')', True
    return src.name(), True
"""

# The input pipe is the source of truth, so renaming the parent never breaks it.
# This only refreshes the display (text field, info line, tile colour).
REFRESH = DESCRIBE + """
n = nuke.thisNode()
info, ok = describe(n)
color = OK_COLOR if ok else 0xFF000000
p = n.input(0)
if p is not None and n['connectNode'].value() != p.name():
    n['connectNode'].setValue(p.name())
if n['parentInfo'].value() != info:
    n['parentInfo'].setValue(info)
if n['tile_color'].value() != color:
    n['tile_color'].setValue(color)
"""

# Only typing in "Connect Node" changes the wire. Other knob changes just refresh.
KNOB_CHANGED = """
n = nuke.thisNode()
if nuke.thisKnob().name() == 'connectNode':
    target = nuke.toNode(n['connectNode'].value())
    if target is not None and target.fullName() == n.fullName():
        target = None
    n.setInput(0, target)
"""

PICK_SELECTED = """
n = nuke.thisNode()
sel = [x for x in nuke.selectedNodes() if x.fullName() != n.fullName()]
if len(sel) == 1:
    n['connectNode'].setValue(sel[0].name())
    n.setInput(0, sel[0])
else:
    nuke.message('Select exactly one node (not this Connect node), then click again.')
"""

GO_TO_PARENT = """
p = nuke.thisNode().input(0)
if p is None:
    nuke.message('This node has no parent.')
else:
    for x in nuke.allNodes():
        x.setSelected(False)
    p.setSelected(True)
    nuke.zoom(nuke.zoom(), [p.xpos() + p.screenWidth() / 2, p.ypos() + p.screenHeight() / 2])
"""

def module_call(call):
    # Button code that calls a function in connect_node.py, with a friendly message if it is missing.
    return ("try:\n    import connect_node\nexcept ImportError:\n"
            "    nuke.message('This needs connect_node.py in your .nuke folder.')\n"
            "else:\n    connect_node." + call + "\n")


# List, tidy, repoint, find-broken and the favourites buttons live in connect_node.py.
LIST_ALL = module_call('list_all()')
PICK_FAVOURITE = module_call('pick_favourite()')

# Opens the real source's properties, skipping any Connect or dummy nodes in between.
OPEN_SOURCE = """
src = nuke.thisNode().input(0)
hops = 0
while src is not None and 'connectNode' in src.knobs() and hops < 20:
    src = src.input(0)
    hops += 1
if src is None or 'connectNode' in src.knobs():
    nuke.message('Nothing to open: this node does not lead to a real source.')
else:
    src.showControlPanel()
"""

SELECT_USERS = """
n = nuke.thisNode()
users = [x for x in nuke.allNodes() if 'connectNode' in x.knobs()
         and x.input(0) is not None and x.input(0).fullName() == n.fullName()]
if users:
    for x in nuke.allNodes():
        x.setSelected(False)
    for x in users:
        x.setSelected(True)
    nuke.message(str(len(users)) + ' node(s) use ' + n.name() + ':\\n' + '\\n'.join(x.name() for x in users))
else:
    nuke.message('No Connect nodes use ' + n.name() + '.')
"""

exec(DESCRIBE)


def all_connects():
    return [x for x in nuke.allNodes() if 'connectNode' in x.knobs()]


def is_dummy(node):
    return 'isDummy' in node.knobs() and bool(node['isDummy'].value())


def jump(target):
    for x in nuke.allNodes():
        x.setSelected(False)
    target.setSelected(True)
    nuke.zoom(nuke.zoom(), [target.xpos() + target.screenWidth() / 2, target.ypos() + target.screenHeight() / 2])


def make_node(dummy=False, source=None):
    # The dummy is the same node in a different colour. Point it at anything,
    # point Connect nodes at the dummy, and re-pointing the dummy moves them all.
    sel = nuke.selectedNodes()
    ref = source if source is not None else (sel[0] if len(sel) == 1 else None)

    name = 'Connect_Node_1'
    if dummy:
        # Cancel stops creation. An empty answer keeps the default name.
        answer = nuke.getInput('Dummy node name', 'Dummy_Node_1')
        if answer is None:
            return None
        name = answer.strip().replace(' ', '_') or 'Dummy_Node_1'
    n = nuke.nodes.NoOp(name=name)
    n['hide_input'].setValue(True)
    n['label'].setValue(LABEL.replace('Connected to', 'Dummy to') if dummy else LABEL)
    n['tile_color'].setValue(BROKEN_COLOR)
    n['note_font_size'].setValue(LABEL_SIZE)
    if ref is not None:
        # Just to the right of the source (or the single selected node).
        n.setXYpos(ref.xpos() + ref.screenWidth() + 30, ref.ypos())

    n.addKnob(nuke.Tab_Knob('User'))
    # Not saved or copied: a stale name from another script can never reconnect
    # an imported node. The wire is the only thing that travels.
    name_knob = nuke.String_Knob('connectNode', 'Connect Node')
    name_knob.setFlag(nuke.DO_NOT_WRITE)
    n.addKnob(name_knob)
    n.addKnob(nuke.Text_Knob('parentInfo', 'Connected To', 'Nothing'))

    marker = nuke.Boolean_Knob('isDummy', 'is dummy')
    marker.setValue(dummy)
    marker.setFlag(nuke.INVISIBLE)
    n.addKnob(marker)

    buttons = [
        ('pickSelected', 'Pick Selected Node', PICK_SELECTED, True),
        ('pickFavourite', 'Pick Favourite', PICK_FAVOURITE, False),
        ('goToParent', 'Go to Parent', GO_TO_PARENT, False),
        ('openSource', 'Open Properties', OPEN_SOURCE, True),
        ('listAll', 'List All Connects', LIST_ALL, False),
    ]
    if dummy:
        buttons.append(('selectUsers', 'Select Users', SELECT_USERS, False))
    for knob_name, label, code, new_line in buttons:
        k = nuke.PyScript_Knob(knob_name, label)
        k.setCommand(code)
        if not new_line:
            k.clearFlag(nuke.STARTLINE)
        n.addKnob(k)

    n.addKnob(nuke.Text_Knob('divider', ''))
    n.addKnob(nuke.Text_Knob('created', '', 'Created by Sid'))

    # Callbacks last, so they never fire while knobs are still being added.
    refresh = REFRESH.replace('OK_COLOR', hex(DUMMY_COLOR if dummy else CONNECT_COLOR))
    n['knobChanged'].setValue(KNOB_CHANGED + refresh)
    n['updateUI'].setValue(refresh)

    if source is not None:
        # Same two steps as the Pick Selected Node button.
        n['connectNode'].setValue(source.name())
        n.setInput(0, source)
    return n


def make_on_selected():
    sel = nuke.selectedNodes()
    if len(sel) != 1:
        nuke.message('Select exactly one node first, then try again.')
        return None
    return make_node(source=sel[0])


_panel = None


def list_all():
    # Searchable, non-modal list. Double-click a row to jump to that node.
    global _panel
    try:
        from PySide6 import QtWidgets, QtGui
    except ImportError:
        from PySide2 import QtWidgets, QtGui

    if not all_connects():
        nuke.message('No Connect nodes found.')
        return
    if _panel is not None:
        _panel.close()

    dlg = QtWidgets.QDialog(QtWidgets.QApplication.activeWindow())
    dlg.setWindowTitle('Connect Nodes')
    dlg.resize(620, 380)
    layout = QtWidgets.QVBoxLayout(dlg)

    search = QtWidgets.QLineEdit()
    search.setPlaceholderText('Filter by node, type, source or status')
    layout.addWidget(search)

    table = QtWidgets.QTreeWidget()
    table.setHeaderLabels(['Node', 'Type', 'Source', 'Status'])
    table.setRootIsDecorated(False)
    table.setColumnWidth(0, 170)
    table.setColumnWidth(1, 70)
    table.setColumnWidth(2, 250)
    layout.addWidget(table)

    def fill(*_):
        table.clear()
        text = search.text().lower()
        for c in all_connects():
            info, ok = describe(c)
            row = [c.fullName(), 'Dummy' if is_dummy(c) else 'Connect', info, 'OK' if ok else 'BROKEN']
            if text and not any(text in cell.lower() for cell in row):
                continue
            item = QtWidgets.QTreeWidgetItem(row)
            if not ok:
                for col in range(4):
                    item.setForeground(col, QtGui.QBrush(QtGui.QColor(230, 70, 70)))
            table.addTopLevelItem(item)

    def picked():
        item = table.currentItem()
        return nuke.toNode(item.text(0)) if item is not None else None

    def go_node(*_):
        node = picked()
        if node is not None:
            jump(node)

    def go_parent(*_):
        node = picked()
        if node is not None and node.input(0) is not None:
            jump(node.input(0))

    def open_source(*_):
        node = picked()
        if node is None:
            return
        src = real_source(node)
        if src is None:
            nuke.message('Nothing to open: this node does not lead to a real source.')
        else:
            src.showControlPanel()

    row_buttons = QtWidgets.QHBoxLayout()
    for label, func in [('Go to Node', go_node), ('Go to Parent', go_parent), ('Open Source', open_source),
                        ('Select Broken', lambda *_: select_broken()), ('Refresh', fill)]:
        button = QtWidgets.QPushButton(label)
        button.clicked.connect(func)
        row_buttons.addWidget(button)
    layout.addLayout(row_buttons)

    search.textChanged.connect(fill)
    table.itemDoubleClicked.connect(go_node)
    fill()
    _panel = dlg
    dlg.show()


def select_broken():
    broken = [c for c in all_connects() if not describe(c)[1]]
    if not broken:
        nuke.message('No broken Connect nodes.')
        return
    for x in nuke.allNodes():
        x.setSelected(False)
    for c in broken:
        c.setSelected(True)
    nuke.message(str(len(broken)) + ' broken node(s) selected (press F in the graph to frame them):\n'
                 + '\n'.join(c.name() for c in broken))


def repoint_all():
    sel = nuke.selectedNodes()
    panel = nuke.Panel('Repoint Connect nodes')
    panel.addSingleLineInput('From (current parent)', sel[0].name() if len(sel) == 1 else '')
    panel.addSingleLineInput('To (new parent)', '')
    if not panel.show():
        return
    old = nuke.toNode(panel.value('From (current parent)').strip())
    new = nuke.toNode(panel.value('To (new parent)').strip())
    if old is None or new is None:
        nuke.message('Both nodes must exist in this graph.')
        return
    if old.fullName() == new.fullName():
        nuke.message('From and To are the same node.')
        return
    users = [c for c in all_connects() if c.input(0) is not None
             and c.input(0).fullName() == old.fullName() and c.fullName() != new.fullName()]
    if not users:
        nuke.message('No Connect nodes point at ' + old.name() + '.')
        return
    if not nuke.ask('Repoint ' + str(len(users)) + ' node(s) from ' + old.name() + ' to ' + new.name()
                    + '?\n' + '\n'.join(c.name() for c in users)):
        return
    failed = []
    for c in users:
        c['connectNode'].setValue(new.name())
        c.setInput(0, new)
        if c.input(0) is None or c.input(0).fullName() != new.fullName():
            failed.append(c.name())
    if failed:
        nuke.message('Could not repoint (Nuke refused, possibly a loop):\n' + '\n'.join(failed))


def tidy():
    # Lines up every Connect and dummy node in a grid, dummies first.
    # Select one node first to put the grid just to its right. Otherwise the grid
    # starts at the top left of the existing Connect nodes.
    nodes = sorted(all_connects(), key=lambda c: (not is_dummy(c), c.name()))
    if not nodes:
        nuke.message('No Connect nodes found.')
        return
    panel = nuke.Panel('Tidy Connect nodes')
    panel.addEnumerationPulldown('Layout', 'Row Column')
    panel.addBooleanCheckBox('Wrap in Backdrop', True)
    if not panel.show():
        return
    if not nuke.ask('Move ' + str(len(nodes)) + ' Connect and dummy node(s) into a grid?'):
        return

    sel = nuke.selectedNodes()
    if len(sel) == 1:
        anchor_x, anchor_y = sel[0].xpos() + sel[0].screenWidth() + 100, sel[0].ypos()
    else:
        anchor_x, anchor_y = min(c.xpos() for c in nodes), min(c.ypos() for c in nodes)

    per_line = 10
    step_x = max(c.screenWidth() for c in nodes) + 30
    step_y = max(c.screenHeight() for c in nodes) + 30
    by_row = panel.value('Layout') == 'Row'
    for i, c in enumerate(nodes):
        along, line = i % per_line, i // per_line
        col, row = (along, line) if by_row else (line, along)
        c.setXYpos(anchor_x + col * step_x, anchor_y + row * step_y)

    if panel.value('Wrap in Backdrop'):
        lines = (len(nodes) + per_line - 1) // per_line
        along_count = min(len(nodes), per_line)
        cols, rows = (along_count, lines) if by_row else (lines, along_count)
        backdrop = nuke.toNode('Connects_Backdrop') or nuke.nodes.BackdropNode(name='Connects_Backdrop')
        backdrop.setXYpos(anchor_x - 20, anchor_y - 60)
        backdrop['bdwidth'].setValue(cols * step_x + 40)
        backdrop['bdheight'].setValue(rows * step_y + 80)
        backdrop['label'].setValue('Connects')
        backdrop['note_font_size'].setValue(40)


def real_source(node):
    # Follows Connect and dummy nodes to the real node behind them.
    src = node.input(0)
    hops = 0
    while src is not None and 'connectNode' in src.knobs() and hops < 20:
        src = src.input(0)
        hops += 1
    return None if src is not None and 'connectNode' in src.knobs() else src


def open_selected_source():
    sel = [x for x in nuke.selectedNodes() if 'connectNode' in x.knobs()]
    if len(sel) != 1:
        nuke.message('Select exactly one Connect or dummy node first.')
        return
    src = real_source(sel[0])
    if src is None:
        nuke.message('Nothing to open: this node does not lead to a real source.')
        return
    src.showControlPanel()


def pick_favourite():
    # Called from the Pick Favourite button on a Connect or dummy node.
    n = nuke.thisNode()
    names = [x for x in fav_names() if nuke.toNode(x) is not None]
    if not names:
        nuke.message('No favourites yet. Open Favourites panel and click Add Selected.')
        return
    panel = nuke.Panel('Pick Favourite')
    panel.addEnumerationPulldown('Favourite', ' '.join(names))
    if panel.show():
        target = nuke.toNode(panel.value('Favourite'))
        if target is not None and target.fullName() != n.fullName():
            n['connectNode'].setValue(target.name())
            n.setInput(0, target)


def _fav_file():
    import os
    return os.path.join(os.path.expanduser('~'), '.nuke', 'sid_favourites.json')


def fav_names():
    # Favourite node names saved in ~/.nuke/sid_favourites.json. No Favourites node needed.
    import json
    try:
        with open(_fav_file()) as fh:
            return [str(x) for x in json.load(fh)]
    except (IOError, OSError, ValueError):
        return []


def fav_save(names):
    import json
    with open(_fav_file(), 'w') as fh:
        json.dump(names, fh, indent=1)


def fav_entries():
    # (name, node) for every saved favourite that exists in the open script.
    out = []
    for name in fav_names():
        node = nuke.toNode(name)
        if node is not None:
            out.append((name, node))
    return out


def selected_nodes_safe():
    # nuke.selectedNodes(), with the TCL selection as a fallback.
    sel = list(nuke.selectedNodes())
    if not sel:
        try:
            for ident in nuke.tcl('selected_nodes').split():
                n = nuke.toNode(nuke.tcl('value %s.name' % ident))
                if n is not None:
                    sel.append(n)
        except Exception:
            pass
    return sel


_fav_panel = None


def favourites_panel():
    # Floating, non-modal list of every favourite in the graph.
    global _fav_panel
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    if _fav_panel is not None:
        _fav_panel.close()

    dlg = QtWidgets.QDialog(QtWidgets.QApplication.activeWindow())
    dlg.setWindowTitle('Favourites')
    dlg.resize(460, 360)
    layout = QtWidgets.QVBoxLayout(dlg)
    search = QtWidgets.QLineEdit()
    search.setPlaceholderText('Filter favourites')
    layout.addWidget(search)
    table = QtWidgets.QTreeWidget()
    table.setHeaderLabels(['Favourite', 'Class'])
    table.setRootIsDecorated(False)
    table.setColumnWidth(0, 260)
    layout.addWidget(table)
    shown = []

    def fill(*_):
        table.clear()
        del shown[:]
        text = search.text().lower()
        for name, fav in fav_entries():
            row = [fav.fullName(), fav.Class()]
            if text and not any(text in cell.lower() for cell in row):
                continue
            table.addTopLevelItem(QtWidgets.QTreeWidgetItem(row))
            shown.append((name, fav))

    def current():
        idx = table.indexOfTopLevelItem(table.currentItem())
        return shown[idx] if idx >= 0 else None

    def add(*_):
        sel = selected_nodes_safe()
        if not sel:
            nuke.message('No node selected in the Node Graph. Click a node there, then click Add Selected.')
            return
        names = fav_names()
        for x in sel:
            if x.fullName() not in names:
                names.append(x.fullName())
        fav_save(names)
        fill()

    def open_props(*_):
        entry = current()
        if entry is not None:
            entry[1].showControlPanel()

    def connect(*_):
        entry = current()
        if entry is not None:
            make_node(source=entry[1])

    def zoom(*_):
        entry = current()
        if entry is not None:
            jump(entry[1])

    def remove(*_):
        entry = current()
        if entry is not None:
            fav_save([n for n in fav_names() if n != entry[0]])
            fill()

    def refresh(*_):
        fill()

    row_buttons = QtWidgets.QHBoxLayout()
    for label, func in [('Add Selected', add), ('Open Properties', open_props), ('Connect', connect),
                        ('Zoom', zoom), ('Remove', remove), ('Refresh', refresh)]:
        button = QtWidgets.QPushButton(label)
        button.clicked.connect(func)
        row_buttons.addWidget(button)
    layout.addLayout(row_buttons)

    search.textChanged.connect(fill)
    table.itemDoubleClicked.connect(open_props)
    fill()
    _fav_panel = dlg
    dlg.show()


ACTIONS = [
    ('Create Connect node on selected', make_on_selected),
    ('Create Connect node', make_node),
    ('Create Dummy node', lambda: make_node(dummy=True)),
    ('List all Connect nodes', list_all),
    ('Select broken Connect nodes', select_broken),
    ('Repoint Connect nodes', repoint_all),
    ('Tidy Connect nodes', tidy),
    ('Favourites panel', favourites_panel),
    ('Open properties of selected Connect source', open_selected_source),
]


def show_menu():
    choice = nuke.choice('Connect', 'What do you want to do?', [label for label, _ in ACTIONS])
    if choice is not None:
        ACTIONS[choice][1]()


def show_qmenu():
    # Popup menu at the mouse cursor, one entry per action. Bound to Ctrl+Tab in menu.py.
    try:
        from PySide6 import QtWidgets, QtGui
    except ImportError:
        from PySide2 import QtWidgets, QtGui
    menu = QtWidgets.QMenu(QtWidgets.QApplication.activeWindow())
    for label, fn in ACTIONS:
        act = menu.addAction(label)
        act.triggered.connect(lambda checked=False, f=fn: f())
    menu.exec_(QtGui.QCursor.pos())


# Only runs when pasted into the Script Editor. Importing from menu.py does nothing.
if __name__ == '__main__':
    show_menu()
