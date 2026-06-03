from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QPushButton, QWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QDialog, QLabel, QTextEdit,
    QLineEdit, QGridLayout, QScrollArea, QComboBox, QListWidget, QAbstractItemView,
    QHBoxLayout, QCheckBox, QListWidgetItem
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QIcon, QBrush, QColor
import etsy_operations
from PyQt5.QtWidgets import QHeaderView

SUBJECT_OPTIONS = [
    "Abstract & geometric", "Animal", "Anime & cartoon", "Architecture & cityscape",
    "Beach & tropical", "Comics & manga", "Fantasy & Sci Fi", "Fashion", "Flowers", "Food & drink",
    "Geography & locale", "Horror & gothic", "Humorous saying", "Inspirational saying",
    "Landscape & scenery", "LGBTQ pride", "Love & friendship", "Military", "Movie", "Music",
    "Nautical", "Patriotic & flags", "People & portrait", "Pet portrait", "Phrase & saying",
    "Plants & trees", "Religious", "Science & tech", "Sports & fitness", "Stars & celestial",
    "Steampunk", "Superhero", "Travel & transportation", "TV", "Video game", "Western & cowboy",
    "Zodiac"
]

HOLIDAY_OPTIONS = [
    "Christmas", "Cinco de Mayo", "Easter", "Father's Day", "Halloween",
    "Hanukkah", "Independence Day", "Kwanzaa", "Lunar New Year", "Mother's Day",
    "New Year's", "Passover", "St Patrick's Day", "Thanksgiving",
    "Valentine's Day", "Veterans Day"
]

OCCASION_OPTIONS = [
    "1st birthday", "Anniversary", "Baby shower", "Bachelor party",
    "Bachelorette party", "Back to school", "Baptism", "Bar & Bat Mitzvah",
    "Birthday", "Bridal shower", "Confirmation", "Divorce & breakup",
    "Engagement", "First Communion", "Graduation", "Grief & mourning",
    "Housewarming", "LGBTQ pride", "Moving", "Pet loss", "Prom",
    "Quinceañera & Sweet 16", "Retirement", "Wedding"
]

COLOR_OPTIONS = [
    "Beige", "Black", "Blue", "Bronze", "Brown", "Clear", "Copper", "Gold", "Gray", "Green",
    "Orange", "Pink", "Purple", "Rainbow", "Red", "Rose gold", "Silver", "White", "Yellow"
]


class MultiSelectDialog(QDialog):
    def __init__(self, title, options, selected=None, limit=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._limit = limit
        selected = selected or []

        layout = QVBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        for option in options:
            item = QListWidgetItem(option)
            self.list_widget.addItem(item)
            if option in selected:
                item.setSelected(True)
        layout.addWidget(self.list_widget)

        buttons_layout = QHBoxLayout()
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Zrušit')
        ok_button.clicked.connect(self._validate_and_accept)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(ok_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _validate_and_accept(self):
        selected = self.get_selected()
        if self._limit is not None and len(selected) > self._limit:
            QMessageBox.warning(self, 'Chyba', f'Můžete vybrat maximálně {self._limit} položek.')
            return
        self.accept()

    def get_selected(self):
        return [item.text() for item in self.list_widget.selectedItems()]

class ProductsTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.products = []
        self._bulk_update = False
        self.table = QTableWidget(0, 14)
        self.table.setHorizontalHeaderLabels([
            'Vybrat', 'Název produktu', 'Miniatura', 'Cena', 'Množství', 'Stav', 'Náhled',
            'Tags', 'Primary Color', 'Secondary Color', 'Subject', 'Holiday', 'Occasion', 'Smazat'
        ])
        for idx in (7, 10, 11, 12):
            self.table.horizontalHeader().setSectionResizeMode(idx, QHeaderView.Stretch)
        self.table.cellChanged.connect(self.cell_changed)
        layout = QVBoxLayout()
        
        filter_layout = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(['Vše', 'Připraven', 'Odesláno', 'Chyba'])
        self.filter_combo.currentTextChanged.connect(self.filter_table)
        filter_layout.addWidget(QLabel('Filtrovat podle stavu:'))
        filter_layout.addWidget(self.filter_combo)
        layout.addLayout(filter_layout)
        
        layout.addWidget(self.table)
        self.setLayout(layout)

    def set_products(self, products):
        self.products = products
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            product.setdefault('subject', [])
            product.setdefault('holiday', [])
            product.setdefault('occasion', [])
            product.setdefault('primary_color', 'Black')
            product.setdefault('secondary_color', 'Black')
            checkbox = QCheckBox()
            checkbox_container = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, checkbox_container)
            
            nazev_item = QTableWidgetItem(product.get('nazev', ''))
            nazev_item.setFlags(nazev_item.flags() | Qt.ItemIsEditable)
            if len(product.get('nazev', '')) > 20:
                nazev_item.setBackground(QBrush(QColor("red")))
            self.table.setItem(row, 1, nazev_item)
            
            if product.get('images'):
                pixmap = QPixmap(product['images'][0]).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon = QIcon(pixmap)
                thumbnail_button = QPushButton()
                thumbnail_button.setIcon(icon)
                thumbnail_button.setIconSize(QSize(50, 50))
                self.table.setCellWidget(row, 2, thumbnail_button)
            else:
                self.table.setItem(row, 2, QTableWidgetItem("Žádný obrázek"))
            
            price_item = QTableWidgetItem(str(product.get('price', '')))
            price_item.setFlags(price_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 3, price_item)
            
            quantity_item = QTableWidgetItem(str(product.get('quantity', '')))
            quantity_item.setFlags(quantity_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 4, quantity_item)
            
            self.table.setItem(row, 5, QTableWidgetItem(product.get('status', 'Připraven')))
            
            preview_button = QPushButton('Náhled')
            preview_button.clicked.connect(lambda checked, r=row: self.show_preview(r))
            self.table.setCellWidget(row, 6, preview_button)
            
            tags_edit = QLineEdit(', '.join(product.get('tags', [])))
            tags_edit.textChanged.connect(lambda text, r=row: self.update_tags(r, text))
            self.table.setCellWidget(row, 7, tags_edit)
            
            primary_color_combo = QComboBox()
            primary_color_combo.addItems(COLOR_OPTIONS)
            primary_color_combo.setCurrentText(product.get('primary_color', 'Black'))
            primary_color_combo.currentTextChanged.connect(lambda text, r=row: self.update_primary_color(r, text))
            self.table.setCellWidget(row, 8, primary_color_combo)
             
            secondary_color_combo = QComboBox()
            secondary_color_combo.addItems(COLOR_OPTIONS)
            secondary_color_combo.setCurrentText(product.get('secondary_color', 'Black'))
            secondary_color_combo.currentTextChanged.connect(lambda text, r=row: self.update_secondary_color(r, text))
            self.table.setCellWidget(row, 9, secondary_color_combo)

            subject_button = QPushButton(self._format_multi_label('Subject', product.get('subject', []), 3))
            subject_button.clicked.connect(lambda checked, r=row: self.update_subject(r))
            self.table.setCellWidget(row, 10, subject_button)

            holiday_button = QPushButton(self._format_multi_label('Holiday', product.get('holiday', [])))
            holiday_button.clicked.connect(lambda checked, r=row: self.update_holiday(r))
            self.table.setCellWidget(row, 11, holiday_button)

            occasion_button = QPushButton(self._format_multi_label('Occasion', product.get('occasion', [])))
            occasion_button.clicked.connect(lambda checked, r=row: self.update_occasion(r))
            self.table.setCellWidget(row, 12, occasion_button)
            
            delete_button = QPushButton('✖')
            delete_button.clicked.connect(lambda checked, r=row: self.delete_product(r))
            self.table.setCellWidget(row, 13, delete_button)

    def cell_changed(self, row, column):
        if column == 1:  # Název produktu
            nazev_item = self.table.item(row, column)
            if nazev_item:
                new_name = nazev_item.text()
                self.products[row]['nazev'] = new_name
                current_subject = list(self.products[row].get('subject', []))
                current_holiday = list(self.products[row].get('holiday', []))
                current_occasion = list(self.products[row].get('occasion', []))
                templates = etsy_operations.load_templates()
                etsy_operations.generate_content(self.products[row], templates['default'])
                self.products[row]['subject'] = current_subject
                self.products[row]['holiday'] = current_holiday
                self.products[row]['occasion'] = current_occasion
                self._refresh_multi_buttons(row)
                if len(new_name) > 20:
                    nazev_item.setBackground(QBrush(QColor("red")))
                else:
                    nazev_item.setBackground(QBrush(QColor("transparent")))
        elif column == 3:  # Cena
            price_item = self.table.item(row, column)
            if price_item:
                try:
                    self.products[row]['price'] = float(price_item.text())
                    self.products[row]['edited'] = True
                except ValueError:
                    QMessageBox.warning(self, 'Chyba', 'Cena musí být číslo.')
        elif column == 4:  # Množství
            quantity_item = self.table.item(row, column)
            if quantity_item:
                try:
                    self.products[row]['quantity'] = int(quantity_item.text())
                    self.products[row]['edited'] = True
                except ValueError:
                    QMessageBox.warning(self, 'Chyba', 'Množství musí být celé číslo.')

    def update_tags(self, row, text):
        self.products[row]['tags'] = [tag.strip() for tag in text.split(',') if tag.strip()]
        self.products[row]['edited'] = True

    def update_primary_color(self, row, text):
        if self._bulk_update:
            return
        self._apply_color_change(row, text, 'primary_color', 8)

    def update_secondary_color(self, row, text):
        if self._bulk_update:
            return
        self._apply_color_change(row, text, 'secondary_color', 9)

    def update_subject(self, row):
        if self._bulk_update:
            return
        self._open_multi_select(row, 'subject', SUBJECT_OPTIONS, 3, 10, 'Subject')

    def update_holiday(self, row):
        if self._bulk_update:
            return
        self._open_multi_select(row, 'holiday', HOLIDAY_OPTIONS, None, 11, 'Holiday')

    def update_occasion(self, row):
        if self._bulk_update:
            return
        self._open_multi_select(row, 'occasion', OCCASION_OPTIONS, None, 12, 'Occasion')

    def _get_row_checkbox(self, row):
        widget = self.table.cellWidget(row, 0)
        if not widget:
            return None
        layout = widget.layout()
        if not layout or layout.count() == 0:
            return None
        checkbox = layout.itemAt(0).widget()
        return checkbox

    def _get_selected_rows(self):
        selected_rows = []
        for row in range(self.table.rowCount()):
            checkbox = self._get_row_checkbox(row)
            if checkbox and checkbox.isChecked():
                selected_rows.append(row)
        return selected_rows

    def get_selected_rows(self):
        return self._get_selected_rows()

    def _apply_color_change(self, row, text, field_name, column_index):
        selected_rows = self._get_selected_rows()
        if selected_rows:
            target_rows = sorted(set(selected_rows + [row]))
        else:
            target_rows = [row]

        self._bulk_update = True
        try:
            for r in target_rows:
                self.products[r][field_name] = text
                self.products[r]['edited'] = True
                combo = self.table.cellWidget(r, column_index)
                if combo and isinstance(combo, QComboBox):
                    combo.blockSignals(True)
                    combo.setCurrentText(text)
                    combo.blockSignals(False)
        finally:
            self._bulk_update = False

    def _format_multi_label(self, label, selected, limit=None):
        count = len(selected)
        if limit:
            return f"{label} ({count}/{limit})"
        return f"{label} ({count})"

    def _refresh_multi_buttons(self, row):
        product = self.products[row]
        subject_button = self.table.cellWidget(row, 10)
        if isinstance(subject_button, QPushButton):
            subject_button.setText(self._format_multi_label('Subject', product.get('subject', []), 3))
        holiday_button = self.table.cellWidget(row, 11)
        if isinstance(holiday_button, QPushButton):
            holiday_button.setText(self._format_multi_label('Holiday', product.get('holiday', [])))
        occasion_button = self.table.cellWidget(row, 12)
        if isinstance(occasion_button, QPushButton):
            occasion_button.setText(self._format_multi_label('Occasion', product.get('occasion', [])))

    def _open_multi_select(self, row, field_name, options, limit, column_index, label):
        current_values = self.products[row].get(field_name, [])
        dialog = MultiSelectDialog(label, options, current_values, limit=limit, parent=self)
        if dialog.exec_():
            selected = dialog.get_selected()
            self._apply_multi_change(row, selected, field_name, column_index, label, limit)

    def apply_ai_metadata(self, row, metadata):
        if row < 0 or row >= len(self.products):
            return
        product = self.products[row]
        self._bulk_update = True
        try:
            primary_color = metadata.get('primary_color')
            secondary_color = metadata.get('secondary_color')
            subjects = [value for value in metadata.get('subject', []) if value in SUBJECT_OPTIONS]
            subjects = list(dict.fromkeys(subjects))
            if len(subjects) < 3:
                for value in product.get('subject', []):
                    if value in SUBJECT_OPTIONS and value not in subjects:
                        subjects.append(value)
                    if len(subjects) >= 3:
                        break
            if len(subjects) < 3:
                for value in SUBJECT_OPTIONS:
                    if value not in subjects:
                        subjects.append(value)
                    if len(subjects) >= 3:
                        break
            subjects = subjects[:3]

            holidays = [value for value in metadata.get('holiday', []) if value in HOLIDAY_OPTIONS][:1]
            occasions = [value for value in metadata.get('occasion', []) if value in OCCASION_OPTIONS][:1]

            if primary_color in COLOR_OPTIONS:
                product['primary_color'] = primary_color
                primary_combo = self.table.cellWidget(row, 8)
                if isinstance(primary_combo, QComboBox):
                    primary_combo.blockSignals(True)
                    primary_combo.setCurrentText(primary_color)
                    primary_combo.blockSignals(False)

            if secondary_color in COLOR_OPTIONS:
                product['secondary_color'] = secondary_color
                secondary_combo = self.table.cellWidget(row, 9)
                if isinstance(secondary_combo, QComboBox):
                    secondary_combo.blockSignals(True)
                    secondary_combo.setCurrentText(secondary_color)
                    secondary_combo.blockSignals(False)

            product['subject'] = subjects
            product['holiday'] = holidays
            product['occasion'] = occasions
            product['edited'] = True

            for key in ('ai_status', 'ai_error', 'ai_confidence', 'ai_model', 'ai_timestamp'):
                if key in metadata:
                    product[key] = metadata[key]

            self._refresh_multi_buttons(row)
        finally:
            self._bulk_update = False

    def _apply_multi_change(self, row, selected, field_name, column_index, label, limit=None):
        selected_rows = self._get_selected_rows()
        if selected_rows:
            target_rows = sorted(set(selected_rows + [row]))
        else:
            target_rows = [row]

        self._bulk_update = True
        try:
            for r in target_rows:
                self.products[r][field_name] = list(selected)
                self.products[r]['edited'] = True
                button = self.table.cellWidget(r, column_index)
                if button and isinstance(button, QPushButton):
                    button.setText(self._format_multi_label(label, selected, limit))
        finally:
            self._bulk_update = False

    def sync_products_from_table(self):
        for row in range(self.table.rowCount()):
            if row >= len(self.products):
                continue
            product = self.products[row]
            name_item = self.table.item(row, 1)
            if name_item:
                product['nazev'] = name_item.text()

            price_item = self.table.item(row, 3)
            if price_item:
                try:
                    product['price'] = float(price_item.text())
                except ValueError:
                    pass

            quantity_item = self.table.item(row, 4)
            if quantity_item:
                try:
                    product['quantity'] = int(quantity_item.text())
                except ValueError:
                    pass

            tags_widget = self.table.cellWidget(row, 7)
            if isinstance(tags_widget, QLineEdit):
                product['tags'] = [tag.strip() for tag in tags_widget.text().split(',') if tag.strip()]

            primary_combo = self.table.cellWidget(row, 8)
            if isinstance(primary_combo, QComboBox):
                product['primary_color'] = primary_combo.currentText()

            secondary_combo = self.table.cellWidget(row, 9)
            if isinstance(secondary_combo, QComboBox):
                product['secondary_color'] = secondary_combo.currentText()

            product['subject'] = [value for value in product.get('subject', []) if value in SUBJECT_OPTIONS][:3]
            product['holiday'] = [value for value in product.get('holiday', []) if value in HOLIDAY_OPTIONS][:1]
            product['occasion'] = [value for value in product.get('occasion', []) if value in OCCASION_OPTIONS][:1]

    def filter_table(self, status):
        for row in range(self.table.rowCount()):
            row_status = self.table.item(row, 5).text()
            self.table.setRowHidden(row, status != 'Vše' and row_status != status)

    def show_preview(self, row):
        dialog = ProductDetailsDialog(self.products[row], self)
        dialog.exec_()
        self.set_products(self.products)

    def delete_product(self, row):
        del self.products[row]
        self.set_products(self.products)

class TemplatesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Úprava šablon')
        self.resize(400, 650)
        self.templates = etsy_operations.load_templates()
        self.current_template = 'default'
        layout = QVBoxLayout()

        self.template_combo = QComboBox()
        self.template_combo.addItems(self.templates.keys())
        self.template_combo.currentTextChanged.connect(self.load_template)
        layout.addWidget(QLabel('Vyberte šablonu:'))
        layout.addWidget(self.template_combo)

        self.title_label = QLabel('Šablona názvu:')
        self.title_edit = QTextEdit()
        layout.addWidget(self.title_label)
        layout.addWidget(self.title_edit)

        self.description_label = QLabel('Šablona popisu:')
        self.description_edit = QTextEdit()
        layout.addWidget(self.description_label)
        layout.addWidget(self.description_edit)

        self.tags_label = QLabel('Šablona tagů:')
        self.tags_edit = QTextEdit()
        layout.addWidget(self.tags_label)
        layout.addWidget(self.tags_edit)

        self.price_label = QLabel('Výchozí cena:')
        self.price_edit = QLineEdit()
        layout.addWidget(self.price_label)
        layout.addWidget(self.price_edit)

        self.quantity_label = QLabel('Výchozí množství:')
        self.quantity_edit = QLineEdit()
        layout.addWidget(self.quantity_label)
        layout.addWidget(self.quantity_edit)

        self.craft_type_label = QLabel('Výchozí typ řemesla:')
        self.craft_type_edit = QLineEdit()
        layout.addWidget(self.craft_type_label)
        layout.addWidget(self.craft_type_edit)

        self.primary_color_label = QLabel('Výchozí primární barva:')
        self.primary_color_combo = QComboBox()
        self.primary_color_combo.addItems(COLOR_OPTIONS)
        layout.addWidget(self.primary_color_label)
        layout.addWidget(self.primary_color_combo)

        self.secondary_color_label = QLabel('Výchozí sekundární barva:')
        self.secondary_color_combo = QComboBox()
        self.secondary_color_combo.addItems(COLOR_OPTIONS)
        layout.addWidget(self.secondary_color_label)
        layout.addWidget(self.secondary_color_combo)

        self.subject_label = QLabel('Vyberte až 3 témata:')
        self.subject_list = QListWidget()
        self.subject_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for subj in SUBJECT_OPTIONS:
            self.subject_list.addItem(QListWidgetItem(subj))
        layout.addWidget(self.subject_label)
        layout.addWidget(self.subject_list)

        self.holiday_label = QLabel('Vyberte Holiday:')
        self.holiday_list = QListWidget()
        self.holiday_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for holiday in HOLIDAY_OPTIONS:
            self.holiday_list.addItem(QListWidgetItem(holiday))
        layout.addWidget(self.holiday_label)
        layout.addWidget(self.holiday_list)

        self.occasion_label = QLabel('Vyberte Occasion:')
        self.occasion_list = QListWidget()
        self.occasion_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for occasion in OCCASION_OPTIONS:
            self.occasion_list.addItem(QListWidgetItem(occasion))
        layout.addWidget(self.occasion_label)
        layout.addWidget(self.occasion_list)

        self.shop_section_label = QLabel('Výchozí ID sekce obchodu:')
        self.shop_section_edit = QLineEdit()
        layout.addWidget(self.shop_section_label)
        layout.addWidget(self.shop_section_edit)

        # Tlačítka pro různé akce
        buttons_layout = QHBoxLayout()
        self.apply_button = QPushButton('Aplikovat na vybrané')
        self.apply_button.clicked.connect(self.apply_to_selected)
        buttons_layout.addWidget(self.apply_button)
        
        self.save_button = QPushButton('Uložit globálně')
        self.save_button.clicked.connect(self.save_templates)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)

        self.load_template('default')
        self.setLayout(layout)

    def load_template(self, template_name):
        self.current_template = template_name
        template = self.templates.get(template_name, {})
        self.title_edit.setText(template.get('title', ''))
        self.description_edit.setText(template.get('description', ''))
        self.tags_edit.setText(template.get('tags', ''))
        self.price_edit.setText(template.get('price', ''))
        self.quantity_edit.setText(template.get('quantity', ''))
        self.craft_type_edit.setText(template.get('craft_type', ''))
        self.primary_color_combo.setCurrentText(template.get('primary_color', 'Black'))
        self.secondary_color_combo.setCurrentText(template.get('secondary_color', 'Black'))
        self.subject_list.clearSelection()
        for i in range(self.subject_list.count()):
            if self.subject_list.item(i).text() in template.get('subject', []):
                self.subject_list.item(i).setSelected(True)
        self.holiday_list.clearSelection()
        for i in range(self.holiday_list.count()):
            if self.holiday_list.item(i).text() in template.get('holiday', []):
                self.holiday_list.item(i).setSelected(True)
        self.occasion_list.clearSelection()
        for i in range(self.occasion_list.count()):
            if self.occasion_list.item(i).text() in template.get('occasion', []):
                self.occasion_list.item(i).setSelected(True)
        self.shop_section_edit.setText(template.get('shop_section_id', ''))

    def get_modified_template(self):
        template = {
            'title': self.title_edit.toPlainText(),
            'description': self.description_edit.toPlainText(),
            'tags': self.tags_edit.toPlainText(),
            'price': self.price_edit.text(),
            'quantity': self.quantity_edit.text(),
            'craft_type': self.craft_type_edit.text(),
            'primary_color': self.primary_color_combo.currentText(),
            'secondary_color': self.secondary_color_combo.currentText(),
            'subject': [item.text() for item in self.subject_list.selectedItems()],
            'holiday': [item.text() for item in self.holiday_list.selectedItems()],
            'occasion': [item.text() for item in self.occasion_list.selectedItems()],
            'shop_section_id': self.shop_section_edit.text()
        }
        if len(template['subject']) > 3:
            QMessageBox.warning(self, 'Chyba', 'Můžete vybrat maximálně 3 témata.')
            return None
        return template

    def apply_to_selected(self):
        modified_template = self.get_modified_template()
        if modified_template:
            self.modified_template = modified_template  # Uložíme pro main.py
            self.accept()

    def save_templates(self):
        modified_template = self.get_modified_template()
        if modified_template:
            self.templates[self.current_template] = modified_template
            etsy_operations.save_templates(self.templates)
            QMessageBox.information(self, 'Šablony uloženy', 'Šablony byly globálně uloženy.')
            self.accept()

class ImagePreviewDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Náhled obrázku')
        layout = QVBoxLayout()
        pixmap = QPixmap(image_path)
        label = QLabel()
        label.setPixmap(pixmap.scaled(800, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(label)
        self.setLayout(layout)

class ProductDetailsDialog(QDialog):
    def __init__(self, product, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Detaily produktu')
        self.resize(800, 800)
        self.product = product
        main_layout = QVBoxLayout()

        self.title_label = QLabel('Název:')
        self.title_edit = QLineEdit(self.product.get('title', self.product.get('nazev', '')))
        main_layout.addWidget(self.title_label)
        main_layout.addWidget(self.title_edit)

        self.description_label = QLabel('Popis:')
        self.description_edit = QTextEdit(self.product.get('description', ''))
        main_layout.addWidget(self.description_label)
        main_layout.addWidget(self.description_edit)

        self.tags_label = QLabel('Tagy:')
        self.tags_edit = QLineEdit(', '.join(self.product.get('tags', [])))
        main_layout.addWidget(self.tags_label)
        main_layout.addWidget(self.tags_edit)

        self.price_label = QLabel('Cena:')
        self.price_edit = QLineEdit(str(self.product.get('price', '')))
        main_layout.addWidget(self.price_label)
        main_layout.addWidget(self.price_edit)

        self.quantity_label = QLabel('Množství:')
        self.quantity_edit = QLineEdit(str(self.product.get('quantity', '')))
        main_layout.addWidget(self.quantity_label)
        main_layout.addWidget(self.quantity_edit)

        self.craft_type_label = QLabel('Typ řemesla:')
        self.craft_type_edit = QLineEdit(self.product.get('craft_type', ''))
        main_layout.addWidget(self.craft_type_label)
        main_layout.addWidget(self.craft_type_edit)

        self.primary_color_label = QLabel('Primární barva:')
        self.primary_color_combo = QComboBox()
        self.primary_color_combo.addItems(COLOR_OPTIONS)
        self.primary_color_combo.setCurrentText(self.product.get('primary_color', 'Black'))
        main_layout.addWidget(self.primary_color_label)
        main_layout.addWidget(self.primary_color_combo)

        self.secondary_color_label = QLabel('Sekundární barva:')
        self.secondary_color_combo = QComboBox()
        self.secondary_color_combo.addItems(COLOR_OPTIONS)
        self.secondary_color_combo.setCurrentText(self.product.get('secondary_color', 'Black'))
        main_layout.addWidget(self.secondary_color_label)
        main_layout.addWidget(self.secondary_color_combo)

        self.subject_label = QLabel('Vyberte až 3 témata:')
        self.subject_list = QListWidget()
        self.subject_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for subj in SUBJECT_OPTIONS:
            item = QListWidgetItem(subj)
            self.subject_list.addItem(item)
            if subj in self.product.get('subject', []):
                item.setSelected(True)
        main_layout.addWidget(self.subject_label)
        main_layout.addWidget(self.subject_list)

        self.holiday_label = QLabel('Vyberte Holiday:')
        self.holiday_list = QListWidget()
        self.holiday_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for holiday in HOLIDAY_OPTIONS:
            item = QListWidgetItem(holiday)
            self.holiday_list.addItem(item)
            if holiday in self.product.get('holiday', []):
                item.setSelected(True)
        main_layout.addWidget(self.holiday_label)
        main_layout.addWidget(self.holiday_list)

        self.occasion_label = QLabel('Vyberte Occasion:')
        self.occasion_list = QListWidget()
        self.occasion_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for occasion in OCCASION_OPTIONS:
            item = QListWidgetItem(occasion)
            self.occasion_list.addItem(item)
            if occasion in self.product.get('occasion', []):
                item.setSelected(True)
        main_layout.addWidget(self.occasion_label)
        main_layout.addWidget(self.occasion_list)

        self.shop_section_label = QLabel('Sekce obchodu:')
        self.shop_section_edit = QLineEdit(str(self.product.get('shop_section_id', '')))
        main_layout.addWidget(self.shop_section_label)
        main_layout.addWidget(self.shop_section_edit)

        images_label = QLabel('Obrázky:')
        main_layout.addWidget(images_label)
        if self.product.get('images'):
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            images_widget = QWidget()
            images_layout = QGridLayout()
            for idx, image_path in enumerate(self.product['images']):
                pixmap = QPixmap(image_path)
                icon = QIcon(pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                button = QPushButton()
                button.setIcon(icon)
                button.setIconSize(QSize(100, 100))
                button.clicked.connect(lambda checked, p=image_path: self.show_image(p))
                images_layout.addWidget(button, idx // 4, idx % 4)
            images_widget.setLayout(images_layout)
            scroll_area.setWidget(images_widget)
            main_layout.addWidget(scroll_area)
        else:
            main_layout.addWidget(QLabel('Žádné obrázky k zobrazení.'))

        self.save_button = QPushButton('Uložit')
        self.save_button.clicked.connect(self.save_changes)
        main_layout.addWidget(self.save_button)

        self.setLayout(main_layout)

    def show_image(self, image_path):
        dialog = ImagePreviewDialog(image_path, self)
        dialog.exec_()

    def save_changes(self):
        self.product['title'] = self.title_edit.text()
        self.product['description'] = self.description_edit.toPlainText()
        self.product['tags'] = [tag.strip() for tag in self.tags_edit.text().split(',')]
        try:
            self.product['price'] = float(self.price_edit.text())
        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Cena musí být číslo.')
            return
        try:
            self.product['quantity'] = int(self.quantity_edit.text())
        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Množství musí být celé číslo.')
            return
        self.product['craft_type'] = self.craft_type_edit.text()
        self.product['primary_color'] = self.primary_color_combo.currentText()
        self.product['secondary_color'] = self.secondary_color_combo.currentText()
        selected_subjects = [item.text() for item in self.subject_list.selectedItems()]
        if len(selected_subjects) > 3:
            QMessageBox.warning(self, 'Chyba', 'Můžete vybrat maximálně 3 témata.')
            return
        self.product['subject'] = selected_subjects
        self.product['holiday'] = [item.text() for item in self.holiday_list.selectedItems()]
        self.product['occasion'] = [item.text() for item in self.occasion_list.selectedItems()]
        self.product['shop_section_id'] = self.shop_section_edit.text()
        self.product['edited'] = True
        QMessageBox.information(self, 'Uloženo', 'Změny byly uloženy.')
        self.accept()
