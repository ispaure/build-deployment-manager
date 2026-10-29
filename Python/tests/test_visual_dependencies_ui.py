"""Reduce map clutter without weakening declared scheduling or failure semantics."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from build_manager import Phase, Plan
from build_manager.workflow_ui import (FlowCanvas, WorkflowFlow, connection_groups,
    connection_color, connection_path, display_states, visible_dependencies)


def step(key, parents=(), **options):
    return Phase(key, (sys.executable, '-V'), '.', dependencies=parents, **options)


class VisualDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_common_utils_links_are_implied_through_each_test_chain(self):
        phases = (step('commonUtils'), step('B', ('commonUtils',)),
                  step('C', ('commonUtils', 'B')), step('D', ('commonUtils', 'B', 'C')))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        self.assertEqual(canvas.edges, [('commonUtils', 'B'), ('B', 'C'), ('C', 'D')])
        self.assertEqual(plan.data(), before)
        states = display_states(plan, {'commonUtils': dict(status='failed')})
        self.assertEqual(states['C'][0], 'blocked')
        self.assertIn('commonUtils', states['C'][1])
        # A filtered drawing cannot imply a connection through a hidden card.
        canvas.reset(plan, {'commonUtils', 'C'})
        self.assertEqual(canvas.edges, [('commonUtils', 'C')])

    def test_fork_join_preserves_both_branches_and_independent_prerequisites(self):
        phases = (step('A'), step('B', ('A',)), step('C', ('A',)), step('independent'),
                  step('join', ('A', 'B', 'C', 'independent')))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'),
            ('B', 'join'), ('C', 'join'), ('independent', 'join')})

    def test_selection_keeps_all_reduced_connections_painted(self):
        phases = (step('A'), step('B', ('A',)), step('C', ('A',)),
                  step('join', ('A', 'B', 'C')), step('cleanup', waits_for=('join',)))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        view = WorkflowFlow(graph_only=True)
        self.addCleanup(view.close)
        view.reset(plan, preview=True)
        view.show()
        self.app.processEvents()
        expected = {('A', 'B'), ('A', 'C'), ('B', 'join'), ('C', 'join'), ('join', 'cleanup')}
        for selected in ('', 'A', 'B', 'join', 'cleanup', ''):
            view.select(selected)
            self.assertEqual(set(view.canvas.edges), expected)
            with patch('build_manager.workflow_cards_ui.connection_path', wraps=connection_path) as draw:
                view.canvas.grab()
            expected_groups = connection_groups(view.canvas.edges, view.canvas.positions,
                view.canvas.order_edges, view.canvas.states, view.canvas.completion_targets)
            self.assertEqual(draw.call_count, len(expected_groups))
        self.assertIn(('join', 'cleanup'), view.canvas.order_edges)
        view.set_scope({'A', 'C'})
        view.select('C')
        self.assertEqual(view.canvas.edges, [('A', 'C')])
        self.assertEqual(plan.data(), before)

    def test_shared_junction_preserves_exact_prerequisites_and_separate_semantics(self):
        positions = {'portable': (0, 0), 'desktop': (0, 2), 'host': (0, 4),
                     'build': (1, 1), 'tools': (1, 3), 'later': (2, 0)}
        edges = [(source, target) for source in ('portable', 'desktop', 'host')
                 for target in ('build', 'tools')]
        groups = connection_groups(edges, positions)
        self.assertEqual(len(groups), 1)
        self.assertEqual({(source, target) for sources, targets, _ in groups
                          for source in sources for target in targets}, set(edges))
        # Different parent sets must not acquire each other's prerequisites.
        partial = edges[:-1]
        groups = connection_groups(partial, positions)
        self.assertEqual(len(groups), 2)
        self.assertEqual({(source, target) for sources, targets, _ in groups
                          for source in sources for target in targets}, set(partial))
        for options in ({'order_edges': {('host', 'tools')}},
                        {'states': {'tools': ('blocked', '')}},
                        {'completion_targets': {'tools'}}):
            self.assertGreater(len(connection_groups(edges, positions, **options)), 1)

    def test_shared_junction_uses_straight_rail_and_horizontal_arrow_entries(self):
        starts = [QPointF(100, y) for y in (50, 150, 250)]
        ends = [QPointF(148, y) for y in (100, 200)]
        path, arrows, junctions = connection_path(starts, ends)
        self.assertEqual(len(arrows), 2)
        self.assertEqual(len(junctions), 5)
        self.assertEqual({point.x() for point in junctions}, {124})
        previous = None
        for index in range(path.elementCount()):
            element = path.elementAt(index)
            if element.isLineTo():
                self.assertTrue(element.x == previous.x or element.y == previous.y)
            previous = element
        for end, arrow in zip(ends, arrows):
            self.assertEqual(arrow[0], end)
            self.assertEqual((arrow[1].y() + arrow[2].y()) / 2, end.y())

    def test_unrelated_groups_get_distinct_rails_in_both_orientations(self):
        phases = (step('host'), step('windows'), step('ios', ('host',)),
                  step('windows-checks', ('windows',)),
                  step('debug', ('ios',)), step('release', ('ios', 'windows-checks')))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        canvas.show()
        for vertical in (False, True):
            canvas.arrange(vertical)
            self.app.processEvents()
            with patch('build_manager.workflow_cards_ui.connection_path', wraps=connection_path) as draw:
                canvas.grab()
            rails = {}
            groups = connection_groups(canvas.edges, canvas.positions)
            for (sources, targets, _), call in zip(groups, draw.call_args_list):
                gap = (canvas.positions[sources[0]][0], canvas.positions[targets[0]][0])
                fraction = call.kwargs['rail_fraction']
                self.assertNotIn(fraction, rails.setdefault(gap, []))
                rails[gap].append(fraction)
                _, _, junctions = connection_path(*call.args, **call.kwargs)
                self.assertTrue(junctions)
            self.assertEqual(len(draw.call_args_list), len(groups))
        self.assertEqual(plan.data(), before)

    def test_shared_and_distinct_host_checks_keep_their_execution_identity(self):
        phases = (step('host-1', label='Host checks'), step('host-2', label='Host checks'),
                  step('ios', ('host-1',)), step('android', ('host-1',)),
                  step('windows', ('host-2',)))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        self.assertEqual(set(canvas.cards), {p.id for p in phases})
        self.assertEqual(set(canvas.edges), {('host-1', 'ios'), ('host-1', 'android'), ('host-2', 'windows')})
        states = display_states(plan, {'host-1': dict(status='failed'), 'host-2': dict(status='passed')})
        self.assertEqual(states['ios'][0], 'blocked')
        self.assertEqual(states['android'][0], 'blocked')
        self.assertNotEqual(states['windows'][0], 'blocked')

    def test_preview_cards_name_prerequisites_without_unrelated_checks(self):
        from PySide6.QtWidgets import QLabel
        from build_manager.proposed_workflow import ProposedStep, ProposedWorkflow
        proposal = ProposedWorkflow((ProposedStep('ios', 'iOS', 'Required checks'),
            ProposedStep('windows', 'Windows', 'Required checks'),
            ProposedStep('debug', 'Build iOS Debug', 'Development variant', ('ios',), 'delivery')))
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(proposal)
        label = canvas.cards['debug'][0].findChild(QLabel, 'workflowPrerequisites')
        self.assertEqual(label.text(), 'Requires: iOS')

    def test_hover_traces_ancestors_and_descendants_without_sibling_branches_or_selection(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QEnterEvent, QFocusEvent
        from PySide6.QtTest import QSignalSpy
        phases = (step('host'), step('ios', ('host',)), step('android', ('host',)),
                  step('windows'), step('build', ('ios',)), step('install', ('build',)))
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        before = plan.data()
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        spy = QSignalSpy(canvas.selected)
        build = canvas.cards['build'][0]
        self.app.sendEvent(build, QEnterEvent(QPointF(), QPointF(), QPointF()))
        self.assertEqual(canvas.trace_keys, {'host', 'ios', 'build', 'install'})
        for key, (card, _, _) in canvas.cards.items():
            self.assertIsNone(card.graphicsEffect())
            self.assertEqual(bool(card.property('traceMuted')), key not in canvas.trace_keys)
            self.assertFalse(card.isHidden())
        with patch('build_manager.workflow_cards_ui.connection_path', wraps=connection_path) as draw:
            canvas.grab()
        self.assertGreater(draw.call_count, len(connection_groups(canvas.edges, canvas.positions)))
        self.app.sendEvent(build, QEvent(QEvent.Type.Leave))
        self.assertFalse(canvas.trace_keys)
        self.assertTrue(all(not card.property('traceMuted') for card, _, _ in canvas.cards.values()))
        self.app.sendEvent(build, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        self.assertEqual(canvas.trace_keys, {'host', 'ios', 'build', 'install'})
        self.app.sendEvent(build, QFocusEvent(QEvent.Type.FocusOut))
        self.assertFalse(canvas.trace_keys)
        self.assertEqual(spy.count(), 0)
        self.assertEqual(plan.data(), before)

    def test_trace_includes_completion_waits_and_hidden_ancestors_and_resets(self):
        phases = (step('host'), step('ios', ('host',)),
                  step('build', waits_for=('ios',)), step('other'))
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        plan = Plan('Fixture', 'Test', {}, phases, '.')
        canvas.reset(plan, {'host', 'build', 'other'})
        canvas.trace_card('build', True)
        self.assertEqual(canvas.trace_keys, {'host', 'ios', 'build'})
        canvas.trace_card('other', True)
        canvas.trace_card('build', False)
        self.assertEqual(canvas.trace_keys, {'other'})
        canvas.reset(plan)
        self.assertFalse(canvas.trace_keys)
        self.assertTrue(all(not card.property('traceMuted') for card, _, _ in canvas.cards.values()))

    def test_gray_cards_and_lines_remain_opaque_in_both_themes(self):
        plan = Plan('Fixture', 'Test', {}, (step('root'), step('child', ('root',)), step('other')), '.')
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(plan)
        for background in ('#202020', '#ffffff'):
            palette = QPalette(canvas.palette())
            palette.setColor(QPalette.ColorRole.Window, QColor(background))
            canvas.setPalette(palette)
            normal_style = canvas.cards['other'][0].styleSheet()
            canvas.trace_card('root', True)
            self.assertEqual(canvas.trace_keys, {'root', 'child'})
            muted = canvas.cards['other'][0]
            self.assertIsNone(muted.graphicsEffect())
            self.assertNotEqual(muted.styleSheet(), normal_style)
            self.assertFalse(muted.isHidden())
            gray = connection_color(palette, muted=True)
            self.assertEqual(gray.alpha(), 255)
            self.assertEqual(gray.red(), gray.green())
            self.assertEqual(gray.green(), gray.blue())
            self.assertGreater(gray.lightness(), 80)
            self.assertLess(gray.lightness(), 200)
            canvas.trace_card('root', False)
            self.assertEqual(muted.styleSheet(), normal_style)

    def test_descendant_trace_follows_completion_waits_without_expanding_join_siblings(self):
        phases = (step('source'), step('ios', ('source',)), step('windows', ('source',)),
                  step('join', ('ios', 'windows')), step('cleanup', waits_for=('join',)))
        canvas = FlowCanvas()
        self.addCleanup(canvas.close)
        canvas.reset(Plan('Fixture', 'Test', {}, phases, '.'))
        canvas.trace_card('ios', True)
        self.assertEqual(canvas.trace_keys, {'source', 'ios', 'join', 'cleanup'})
        self.assertTrue(canvas.cards['windows'][0].property('traceMuted'))

    def test_muted_cards_are_painted_inside_the_scaled_graph_view(self):
        from build_manager.workflow_ui import FitMapView
        plan = Plan('Fixture', 'Test', {}, (step('ios'), step('windows'), step('build', ('ios',))), '.')
        canvas = FlowCanvas()
        view = FitMapView(canvas)
        self.addCleanup(view.close)
        canvas.reset(plan)
        canvas.update_facts(plan, {}, '', preview=True)
        view.resize(1400, 900)
        view.show()
        self.app.processEvents()
        muted = canvas.cards['windows'][0]
        for background, expected in (('#202020', '#343434'), ('#ffffff', '#e4e4e4')):
            palette = QPalette(canvas.palette())
            palette.setColor(QPalette.ColorRole.Window, QColor(background))
            canvas.setPalette(palette)
            for vertical in (False, True):
                canvas.arrange(vertical)
                # Direct canvas rearrangement bypasses the view's orientation
                # control; synchronize its scene extent before manual zoom.
                view.fit_mode = False
                view.fit_map()
                for scale in (.65, 1.2):
                    with self.subTest(background=background, vertical=vertical, scale=scale):
                        view.resetTransform()
                        view.scale(scale, scale)
                        self.app.processEvents()
                        canvas.trace_card('build', True)
                        # Windows font metrics can make the vertical canvas
                        # taller than the viewport at this zoom. Inspect the
                        # target card, rather than sampling off-screen pixels.
                        view.centerOn(view.proxy.mapToScene(QPointF(muted.geometry().center())))
                        self.app.processEvents()
                        screenshot = view.viewport().grab().toImage()
                        ratio = screenshot.devicePixelRatio()
                        # Sample separated corners: an effect can paint only a
                        # clipped part of the card when embedded in a proxy.
                        for x, y in ((8, 8), (8, muted.height() - 8),
                                     (muted.width() - 8, muted.height() - 8)):
                            point = QPointF(muted.x() + x, muted.y() + y)
                            position = view.mapFromScene(view.proxy.mapToScene(point))
                            sample = QPoint(round(position.x() * ratio), round(position.y() * ratio))
                            self.assertTrue(screenshot.rect().contains(sample),
                                f'Card corner {sample.toTuple()} outside {screenshot.size().toTuple()}; '
                                f'canvas={canvas.size().toTuple()}, card={muted.geometry().getRect()}, '
                                f'viewport={view.viewport().size().toTuple()}, scale={view.transform().m11()}, '
                                f'scene={view.sceneRect().getRect()}')
                            actual = screenshot.pixelColor(sample)
                            self.assertEqual(actual.name(), expected)
                        canvas.trace_card('build', False)

    def test_embedded_hover_covers_card_text_icons_and_suppresses_popups(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QHelpEvent, QMouseEvent
        from PySide6.QtTest import QSignalSpy
        from PySide6.QtWidgets import QLabel, QToolTip
        from build_manager.proposed_workflow import ProposedStep, ProposedWorkflow
        from build_manager.workflow_icons import WorkflowIcons
        from build_manager.workflow_ui import FitMapView
        plan = ProposedWorkflow((ProposedStep('ios', 'iOS', 'Required checks', platforms=('ios',)),
            ProposedStep('windows', 'Windows', 'Required checks', platforms=('windows',)),
            ProposedStep('build', 'Build iOS', 'Debug', ('ios',), 'delivery', platforms=('ios',))))
        canvas = FlowCanvas()
        view = FitMapView(canvas)
        self.addCleanup(view.close)
        canvas.reset(plan)
        canvas.update_facts(plan, {}, '', preview=True)
        view.resize(1100, 700)
        view.show()
        view.set_pointer_follow(False)
        self.app.processEvents()
        spy = QSignalSpy(canvas.selected)
        for vertical in (False, True):
            canvas.arrange(vertical)
            view.fit_map(force=True)
            self.app.processEvents()
            for key in ('ios', 'windows', 'build'):
                card = canvas.cards[key][0]
                widgets = [card, *card.findChildren(QLabel), *card.findChildren(WorkflowIcons)]
                for widget in widgets:
                    if widget.isHidden():
                        continue
                    with self.subTest(vertical=vertical, key=key, widget=type(widget).__name__):
                        center = widget.rect().center()
                        point = center if widget is card else widget.mapTo(card, center)
                        position = view.mapFromScene(view.proxy.mapToScene(QPointF(card.pos() + point)))
                        # Simulate a proxy leave before a child delivers movement.
                        self.app.sendEvent(card, QEvent(QEvent.Type.Leave))
                        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(position),
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                        self.app.sendEvent(view.viewport(), move)
                        self.assertEqual(canvas.hover_key, key)
                        self.assertIn(key, canvas.trace_keys)
                        self.app.sendEvent(view.viewport(), QHelpEvent(QEvent.Type.ToolTip, position,
                            view.viewport().mapToGlobal(position)))
                        self.app.processEvents()
                        self.assertFalse(QToolTip.isVisible())
                        self.assertEqual(canvas.hover_key, key)
        self.app.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
        self.assertFalse(canvas.hover_key)
        self.assertEqual(spy.count(), 0)

    def test_cleanup_cannot_hide_a_success_requirement(self):
        phases = (step('A'), step('cleanup', ('A',), always=True), step('C', ('A', 'cleanup')))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'cleanup'), ('A', 'C'), ('cleanup', 'C')})
        # Cleanup needs completion, which is already implied through B.
        phases = (step('A'), step('B', ('A',)), step('cleanup', ('A', 'B'), always=True))
        self.assertEqual(set(visible_dependencies(phases)),
            {('A', 'B'), ('B', 'cleanup')})

    def test_cleanup_fan_in_drops_ancestors_but_keeps_independent_leaves(self):
        phases = (step('commonutils'), step('portable', ('commonutils',)),
                  step('desktop', ('commonutils',)), step('host', ('commonutils',)),
                  step('build', ('portable', 'desktop', 'host')),
                  step('tools', ('portable', 'desktop', 'host')),
                  step('ready', ('build', 'tools')),
                  step('native', ('ready',)), step('runtime', ('ready',)),
                  step('cleanup', ('commonutils', 'portable', 'desktop', 'host',
                                   'build', 'tools', 'ready', 'native', 'runtime'), always=True))
        edges = visible_dependencies(phases)
        self.assertEqual({source for source, target in edges if target == 'cleanup'}, {'native', 'runtime'})
        self.assertIn(('commonutils', 'portable'), edges)
        self.assertIn(('portable', 'build'), edges)
        # Completion-only paths can simplify cleanup, but not success gates.
        phases = (step('A'), step('B', waits_for=('A',)),
                  step('cleanup', ('A', 'B'), always=True))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('B', 'cleanup')})

    def test_completion_waits_do_not_imply_success_and_stay_visible(self):
        phases = (step('A'), step('B', waits_for=('A',)), step('C', ('A', 'B')))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
        phases = (step('A'), step('B', ('A',)), step('C', ('B',), waits_for=('A',)))
        self.assertEqual(set(visible_dependencies(phases)), {('A', 'B'), ('A', 'C'), ('B', 'C')})
