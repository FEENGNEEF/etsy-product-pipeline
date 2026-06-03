import sys
import json
from datetime import datetime
from typing import Any, Dict
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QFileDialog, QMessageBox, QPushButton,
    QProgressDialog, QInputDialog
)
from PyQt5.QtCore import Qt
from concurrent.futures import ThreadPoolExecutor
import etsy_operations
import ai_metadata
from gui_components import ProductsTable, TemplatesDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Etsy Bulk Lister')
        self.resize(800, 600)
        self.products = []
        self.ACCESS_TOKEN_FILE = 'access_token.txt'
        try:
            with open(self.ACCESS_TOKEN_FILE, 'r') as f:
                self.access_token = f.read().strip()
        except FileNotFoundError:
            self.access_token = None
            QMessageBox.warning(self, 'Chyba autentizace', 'Chybí access_token.txt.')
        self.create_menu()
        self.create_ui()

    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('Soubor')
        load_action = QAction('Načíst produkty', self)
        load_action.triggered.connect(self.load_products)
        load_action.setShortcut('Ctrl+O')
        file_menu.addAction(load_action)
        save_action = QAction('Uložit projekt', self)
        save_action.triggered.connect(self.save_project)
        save_action.setShortcut('Ctrl+S')
        file_menu.addAction(save_action)
        open_action = QAction('Otevřít projekt', self)
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)
        exit_action = QAction('Ukončit', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        settings_menu = menubar.addMenu('Nastavení')
        templates_action = QAction('Šablony', self)
        templates_action.triggered.connect(self.edit_templates)
        settings_menu.addAction(templates_action)
        test_api_action = QAction('Test Etsy API', self)
        test_api_action.triggered.connect(self.test_etsy_api)
        settings_menu.addAction(test_api_action)

    def create_ui(self):
        self.products_table = ProductsTable(self)
        self.setCentralWidget(self.products_table)
        ai_all_button = QPushButton('AI doplnit vše')
        ai_all_button.clicked.connect(self.ai_fill_all)
        self.statusBar().addPermanentWidget(ai_all_button)
        ai_selected_button = QPushButton('AI doplnit vybrané')
        ai_selected_button.clicked.connect(self.ai_fill_selected)
        self.statusBar().addPermanentWidget(ai_selected_button)
        send_button = QPushButton('Odeslat na Etsy')
        send_button.clicked.connect(self.send_to_etsy)
        self.statusBar().addPermanentWidget(send_button)

    def ai_fill_all(self):
        self._run_ai_fill(selected_only=False)

    def ai_fill_selected(self):
        self._run_ai_fill(selected_only=True)

    def _run_ai_fill(self, selected_only: bool):
        if not self.products:
            QMessageBox.warning(self, 'AI metadata', 'Nejprve načtěte produkty.')
            return

        self.products_table.sync_products_from_table()
        if selected_only:
            target_rows = self.products_table.get_selected_rows()
            if not target_rows:
                QMessageBox.information(self, 'AI metadata', 'Nejsou vybrané žádné produkty.')
                return
            label = 'Doplňuji AI metadata (vybrané)...'
        else:
            target_rows = list(range(len(self.products)))
            label = 'Doplňuji AI metadata (vše)...'

        progress = QProgressDialog(label, 'Zrušit', 0, len(target_rows), self)
        progress.setWindowModality(Qt.WindowModal)

        ok_count = 0
        fallback_count = 0
        error_count = 0

        for index, row in enumerate(target_rows):
            progress.setValue(index)
            QApplication.processEvents()
            if progress.wasCanceled():
                break

            product = self.products[row]
            try:
                metadata = ai_metadata.enrich_product_metadata(product)
                self.products_table.apply_ai_metadata(row, metadata)
                if metadata.get('ai_status') == 'ok':
                    ok_count += 1
                elif metadata.get('ai_status') == 'fallback':
                    fallback_count += 1
                else:
                    error_count += 1
            except Exception as exc:
                error_count += 1
                product['ai_status'] = 'error'
                product['ai_error'] = str(exc)
                print(f"AI metadata chyba pro produkt {product.get('nazev', '')}: {exc}")

        progress.setValue(len(target_rows))
        QMessageBox.information(
            self,
            'AI metadata dokončeno',
            f"Zpracováno: {len(target_rows)}\n"
            f"OK (LLM): {ok_count}\n"
            f"Fallback (heuristika): {fallback_count}\n"
            f"Chyby: {error_count}"
        )

    def load_products(self):
        folder = QFileDialog.getExistingDirectory(self, 'Vyberte kořenovou složku projektu')
        if folder:
            templates = etsy_operations.load_templates()
            template_name, ok = QInputDialog.getItem(self, 'Vyberte šablonu', 
                                                    'Vyberte šablonu pro načtení produktů:', 
                                                    list(templates.keys()), 0, False)
            if ok:
                self.products = etsy_operations.load_products(folder, template_name)
                self.products_table.set_products(self.products)

    def save_project(self):
        filename, _ = QFileDialog.getSaveFileName(self, 'Uložit projekt', filter='JSON Files (*.json)')
        if filename:
            self.products_table.sync_products_from_table()
            with open(filename, 'w', encoding='utf-8') as f:
                payload = {
                    'schema_version': 2,
                    'saved_at': datetime.utcnow().isoformat() + 'Z',
                    'products': self.products
                }
                json.dump(payload, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, 'Projekt uložen', 'Projekt byl úspěšně uložen.')

    def open_project(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Otevřít projekt', filter='JSON Files (*.json)')
        if filename:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    products = data.get('products', [])
                elif isinstance(data, list):
                    products = data
                else:
                    products = []
            self.products = [self._normalize_product(p) for p in products if isinstance(p, dict)]
            self.products_table.set_products(self.products)
            QMessageBox.information(self, 'Projekt načten', 'Projekt byl úspěšně načten.')

    def _normalize_product(self, product: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(product, dict):
            return {'nazev': ''}
        product.setdefault('nazev', '')
        product.setdefault('subject', [])
        product.setdefault('holiday', [])
        product.setdefault('occasion', [])
        product.setdefault('tags', [])
        product.setdefault('primary_color', 'Black')
        product.setdefault('secondary_color', 'Black')
        product.setdefault('status', 'Připraven')
        product.setdefault('images', [])
        product.setdefault('video', None)
        product.setdefault('image_count', 0)
        product.setdefault('quantity', 0)
        product.setdefault('price', 0.0)
        product.setdefault('shop_section_id', '')
        product.setdefault('ai_status', '')
        product.setdefault('ai_error', '')
        product.setdefault('ai_confidence', 0.0)
        product.setdefault('ai_model', '')
        product.setdefault('ai_timestamp', '')
        product.setdefault('last_error', '')
        return product

    def edit_templates(self):
        dialog = TemplatesDialog(self)
        if dialog.exec_():  # Pokud dialog skončí
            # Zjistíme vybrané řádky
            selected_rows = [row for row in range(self.products_table.table.rowCount()) 
                            if self.products_table.table.cellWidget(row, 0).layout().itemAt(0).widget().isChecked()]
            all_rows = list(range(self.products_table.table.rowCount()))
            print(f"Selected rows: {selected_rows}, All rows: {all_rows}")  # Debug

            # Pokud šablony v dialogu neodpovídají načteným, znamená to "Uložit globálně"
            original_templates = etsy_operations.load_templates()
            if dialog.templates != original_templates:
                print("Globální uložení detekováno")  # Debug
                target_rows = all_rows
                template = dialog.templates['default']
                for row in target_rows:
                    print(f"Aplikuji globální šablonu na produkt {self.products[row]['nazev']}")  # Debug
                    etsy_operations.generate_content(self.products[row], template)
                    self.products[row]['edited'] = True
                QMessageBox.information(self, 'Šablony uloženy', 'Šablona byla globálně uložena a aplikována na všechny produkty.')
            # Jinak jde o "Aplikovat na vybrané"
            elif hasattr(dialog, 'modified_template'):
                template = dialog.modified_template
                if selected_rows:  # Některé řádky vybrané
                    target_rows = selected_rows
                    print(f"Aplikuji šablonu na vybrané řádky: {target_rows}")  # Debug
                    for row in target_rows:
                        print(f"Aplikuji na produkt {self.products[row]['nazev']}")  # Debug
                        etsy_operations.generate_content(self.products[row], template)
                        self.products[row]['edited'] = True
                    QMessageBox.information(self, 'Změny aplikovány', f'Změny byly aplikovány na {len(target_rows)} vybraných produktů.')
                else:  # Žádné řádky vybrané
                    target_rows = all_rows
                    print("Žádné řádky vybrané, aplikuji na všechny")  # Debug
                    for row in target_rows:
                        print(f"Aplikuji na produkt {self.products[row]['nazev']}")  # Debug
                        etsy_operations.generate_content(self.products[row], template)
                        self.products[row]['edited'] = True
                    QMessageBox.information(self, 'Změny aplikovány', 'Žádné produkty nebyly vybrány, změny aplikovány na všechny.')

            # Aktualizujeme tabulku
            self.products_table.set_products(self.products)
            print("Tabulka aktualizována")  # Debug

    def send_to_etsy(self):
        if not self.access_token:
            QMessageBox.warning(self, 'Chyba', 'Nejste autentizováni.')
            return
        if not self.products:
            QMessageBox.warning(self, 'Chyba', 'Žádné produkty k odeslání.')
            return
        self.products_table.sync_products_from_table()
        progress = QProgressDialog("Odesílám na Etsy...", "Zrušit", 0, len(self.products), self)
        progress.setWindowModality(Qt.WindowModal)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(etsy_operations.upload_listing, p, self.access_token): p for p in self.products}
            for i, future in enumerate(futures):
                progress.setValue(i)
                if progress.wasCanceled():
                    executor.shutdown(wait=False)
                    break
                product = futures[future]
                try:
                    product['status'] = 'Odesláno' if future.result() else 'Chyba'
                    if product['status'] == 'Odesláno':
                        product['last_error'] = ''
                except Exception as exc:
                    product['status'] = 'Chyba'
                    product['last_error'] = str(exc)
                    print(f"Upload selhal pro produkt {product.get('nazev', '')}: {exc}")
        progress.setValue(len(self.products))
        self.products_table.set_products(self.products)
        QMessageBox.information(self, 'Odeslání dokončeno', 'Všechny produkty byly zpracovány.')

    def test_etsy_api(self):
        if not self.access_token:
            QMessageBox.warning(self, 'Chyba', 'Nejste autentizováni.')
            return
        try:
            status, body = etsy_operations.test_ping(self.access_token)
            QMessageBox.information(self, 'Test Etsy API', f"Status: {status}\n{body}")
        except Exception as exc:
            QMessageBox.critical(self, 'Test Etsy API', f"Chyba: {exc}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
