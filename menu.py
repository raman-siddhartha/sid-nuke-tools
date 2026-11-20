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
_cm.addCommand('Quick Connect', connect_node.quick_connect, 'ctrl+Tab')
_cm.addCommand('Connect Selected Node', connect_node.make_on_selected)
_cm.addCommand('Create Dummy Node', lambda: connect_node.make_node(dummy=True))
_cm.addSeparator()
_cm.addCommand('List All Connect Nodes', connect_node.list_all)
_cm.addCommand('Favourites Panel', connect_node.favourites_panel)
_cm.addSeparator()
_mm = _cm.addMenu('Maintenance')
_mm.addCommand('Select Broken', connect_node.select_broken)
_mm.addCommand('Repoint All', connect_node.repoint_all)
_mm.addCommand('Tidy', connect_node.tidy)
_mm.addCommand('Open Source Properties', connect_node.open_selected_source)
