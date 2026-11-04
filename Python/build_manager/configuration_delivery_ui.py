"""Project-declared delivery groups with selected options directly in place."""
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt


def delivery_tab_label(category):
    return {'Mobile tester platforms': 'Tester delivery', 'Mobile dev devices': 'Development devices',
            'Mobile stores': 'Stores', 'Source releases': 'Source releases'}.get(category, category)


class DeliveryOptionsView(QWidget):
    """Own destination forms; configuration owns intent, selection and planning.

    Categories and platform headings share one scrolling form. Selecting a card
    reveals its existing control, without navigating through nested tab bars.
    """
    def __init__(self, capability, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.destination_checks, self.delivery_widgets = {}, []
        self.destination_options, self.destination_forms, self.destination_groups = {}, {}, {}
        self.delivery_categories, self.destination_categories = {}, {}
        self.delivery_platform_pages, self.platform_headings, self.destination_platforms = {}, {}, {}
        if not capability:
            note = QLabel('Integrated delivery is not declared by this project. Choose Project operation for its workflows.')
            note.setWordWrap(True)
            layout.addWidget(note)
            return

        def category(name, platforms):
            if name not in self.delivery_categories:
                group = QGroupBox(delivery_tab_label(name))
                body = QVBoxLayout(group)
                body.setSpacing(12)
                layout.addWidget(group)
                self.delivery_categories[name] = group, body
            body = self.delivery_categories[name][1]
            if len(platforms) == 1:
                platform = platforms[0]
                pages = self.delivery_platform_pages.setdefault(name, {})
                if platform not in pages:
                    page = QWidget()
                    rows = QVBoxLayout(page)
                    rows.setContentsMargins(0, 0, 0, 0)
                    rows.setSpacing(12)
                    heading = QLabel({'ios': 'iOS', 'android': 'Android'}.get(platform, platform))
                    heading.setStyleSheet('font-weight: 600;')
                    rows.addWidget(heading)
                    self.platform_headings[name, platform] = heading
                    body.addWidget(page)
                    pages[platform] = page, rows
                return pages[platform][1]
            return body

        order = {'Mobile tester platforms': 0, 'Mobile dev devices': 1, 'Mobile stores': 2, 'Source releases': 3}
        for name, row in sorted(capability.get('destinations', {}).items(),
                                key=lambda item: order.get(item[1].get('category'), 4)):
            group = QWidget()
            rows = QVBoxLayout(group)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(8)
            control = QCheckBox(row['label'])
            control.setToolTip('Select to show options. Requires: ' + ', '.join(row['platforms']))
            self.destination_checks[name] = control
            rows.addWidget(control)
            options = QWidget()
            options.setAccessibleName(row['label'] + ' options')
            option_rows = QVBoxLayout(options)
            option_rows.setContentsMargins(24, 0, 0, 8)
            option_rows.setSpacing(8)
            explanation = QLabel(row.get('description', '') +
                (' Requires: ' + ', '.join(row['platforms']) if row['platforms'] else ''))
            explanation.setWordWrap(True)
            explanation.setTextFormat(Qt.TextFormat.PlainText)
            explanation.setVisible(bool(explanation.text().strip()))
            option_rows.addWidget(explanation)
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setVerticalSpacing(8)
            option_rows.addLayout(form)
            self.destination_options[name], self.destination_forms[name] = options, form
            self.destination_groups[name] = group
            rows.addWidget(options)
            label = row.get('category', 'Destinations')
            category(label, row.get('platforms', ())).addWidget(group)
            self.destination_categories[name] = label
            self.destination_platforms[name] = row['platforms'][0] if len(row['platforms']) == 1 else ''
            self.delivery_widgets.append(group)
        for row in capability.get('unavailable_destinations', []):
            label = QLabel(row['label'] + ' · unavailable in this workflow\n' + row['reason'])
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            category(row.get('category', 'Destinations'), row.get('platforms', ())).addWidget(label)
