import sid_match_tools
sid_match_tools.install_menu()

import sid_alpha_edge
sid_alpha_edge.install_menu()

import sid_lens_flare
sid_lens_flare.install_menu()

import sid_edge_extend
sid_edge_extend.install_menu()

import sid_light_wrap
sid_light_wrap.install_menu()

import nuke
import connect_node
_cm = nuke.menu('Nodes').addMenu('Sid', icon=None).addMenu('Connect')
_cm.addCommand('Connect Menu...', connect_node.show_qmenu, 'ctrl+Tab')
_cm.addSeparator()
for _label, _fn in connect_node.ACTIONS:
    _cm.addCommand(_label, _fn)
