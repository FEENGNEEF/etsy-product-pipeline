import os
import glob
import json
import re
from string import Template
import requests
try:
    from requests_toolbelt.multipart.encoder import MultipartEncoder
except ImportError:
    MultipartEncoder = None
from typing import List, Dict, Optional, Tuple
from copy import deepcopy
from etsy_oauth import CLIENT_ID, CLIENT_SECRET

TEMPLATES_FILE = os.getenv(
    "ETSY_TEMPLATES_FILE",
    os.path.join(os.path.dirname(__file__), "templates.example.json")
)
SHOP_ID = os.getenv("ETSY_SHOP_ID", "")
PRODUCT_NAME_SUFFIXES = [
    suffix.strip()
    for suffix in os.getenv("PRODUCT_NAME_SUFFIXES", "").split(",")
    if suffix.strip()
]

def build_headers(access_token: Optional[str], content_type: Optional[str] = None) -> Dict[str, str]:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("Chybi ETSY_CLIENT_ID nebo ETSY_CLIENT_SECRET.")
    if not SHOP_ID:
        raise ValueError("Chybi ETSY_SHOP_ID.")
    headers = {'x-api-key': f"{CLIENT_ID}:{CLIENT_SECRET}"}
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    if content_type:
        headers['Content-Type'] = content_type
    return headers

def log_headers_safe(headers: Dict[str, str], context: str = "") -> None:
    api_key = headers.get('x-api-key', '')
    auth = headers.get('Authorization', '')
    prefix = f"{context} " if context else ""
    print(f"{prefix}x-api-key contains_colon={':' in api_key} length={len(api_key)}; Authorization startswith Bearer={auth.startswith('Bearer ')}")

def _format_tag_debug(tags: List[str]) -> List[str]:
    return [f"{tag} ({len(tag)})" for tag in tags]

def _normalize_tag(tag: str) -> str:
    tag = re.sub(r'\s+', ' ', str(tag)).strip()
    if not tag:
        return ''
    cleaned = []
    for ch in tag:
        if ch.isalnum() or ch == ' ' or ch in ("'", "-"):
            cleaned.append(ch)
    tag = ''.join(cleaned)
    tag = re.sub(r'\s+', ' ', tag).strip()
    tag = tag.strip("'- ")
    tag = re.sub(r'\s+', ' ', tag).strip()
    return tag

def _trim_tag(tag: str, max_length: int = 20) -> str:
    if len(tag) <= max_length:
        return tag
    cut = tag[:max_length].rstrip()
    if ' ' in cut:
        cut = cut[:cut.rfind(' ')].rstrip()
    if not cut:
        cut = tag[:max_length].rstrip()
    return cut.strip("'- ")

def sanitize_tags(tags: List[str]) -> List[str]:
    original_tags = [str(tag) for tag in tags if tag is not None]
    sanitized: List[str] = []
    seen = set()
    for raw in original_tags:
        tag = _normalize_tag(raw)
        if not tag:
            continue
        tag = _trim_tag(tag, 20)
        tag = _normalize_tag(tag)
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(tag)
        if len(sanitized) >= 13:
            break
    print(f"Tagy pred sanitizaci: {_format_tag_debug(original_tags)}")
    print(f"Tagy po sanitizaci: {_format_tag_debug(sanitized)}")
    return sanitized

def is_valid_upload_filename(filename: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9._-]{3,70}', filename))

def sanitize_upload_filename(filename: str) -> str:
    base, ext = os.path.splitext(filename)
    safe_base = re.sub(r'[^A-Za-z0-9._-]', '', base)
    safe_ext = re.sub(r'[^A-Za-z0-9]', '', ext.lstrip('.'))
    if ext and not safe_ext:
        safe_ext = 'zip'
    if not safe_base:
        safe_base = 'file'

    safe_name = f"{safe_base}.{safe_ext}" if safe_ext else safe_base
    max_len = 70
    if len(safe_name) > max_len:
        ext_len = len(safe_ext) + 1 if safe_ext else 0
        max_base_len = max_len - ext_len
        if max_base_len < 1:
            safe_base = 'file'
            if safe_ext:
                safe_ext = safe_ext[:max(0, max_len - len(safe_base) - 1)]
            safe_name = f"{safe_base}.{safe_ext}" if safe_ext else safe_base
        else:
            safe_base = safe_base[:max_base_len]
            safe_name = f"{safe_base}.{safe_ext}" if safe_ext else safe_base

    if len(safe_name) < 3:
        safe_name = 'file.zip' if safe_ext else 'file'
    if not is_valid_upload_filename(safe_name):
        safe_name = 'file.zip' if safe_ext else 'file'
    return safe_name

def test_ping(access_token: Optional[str] = None) -> Tuple[int, str]:
    url = 'https://openapi.etsy.com/v3/application/openapi-ping'
    headers = build_headers(access_token)
    log_headers_safe(headers, context='ping')
    response = requests.get(url, headers=headers)
    body = response.text
    print(f"Ping status: {response.status_code}")
    print(f"Ping body: {body}")
    return response.status_code, body

def trim_title(title: str, max_length: int = 140) -> str:
    if len(title) <= max_length:
        return title
    words = title.split()
    while words and len(" ".join(words)) > max_length:
        words.pop()
    return " ".join(words)

def load_templates() -> Dict[str, Dict[str, any]]:
    default_template = {
        'title': '{{nazev}} Digital Download - <<x>> Files',
        'description': (
            "Introducing {{nazev}}, a digital download bundle prepared for creative projects.\n\n"
            "This placeholder template is included only as a public example. Replace it with your own product description, license terms, delivery notes, and printing instructions before using the uploader with a real Etsy shop.\n\n"
            "Delivery:\n"
            "After purchase, customers receive digital files through Etsy's download system.\n\n"
            "Printing:\n"
            "Colors may vary depending on display and printer settings."
        ),
        'tags': '{{nazev}}, digital download, printable art, instant download, wall art, creative assets',
        'price': '5.99',
        'quantity': '999',
        'craft_type': '',
        'primary_color': '',
        'secondary_color': '',
        'subject': [],
        'holiday': [],
        'occasion': [],
        'shop_section_id': '',
    }
    
    if os.path.exists(TEMPLATES_FILE):
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                if 'templates' in data:
                    return data['templates']
                elif 'default' in data:
                    return data
            return {'default': default_template}
    return {'default': default_template}

def save_templates(templates: Dict[str, Dict[str, any]]) -> None:
    dir_path = os.path.dirname(TEMPLATES_FILE)
    os.makedirs(dir_path, exist_ok=True)
    with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
        json.dump(templates, f, ensure_ascii=False, indent=4)

def generate_content(product: Dict[str, any], template: Dict[str, any]) -> None:
    """Aktualizuje pouze ty atributy produktu, které jsou explicitně definovány v šabloně."""
    image_count_str = str(product.get('image_count', 0))
    nazev = product['nazev']
    print(f"Zpracovávám produkt: {nazev}, image_count: {image_count_str}")  # Debug
    
    if 'title' in template:
        product['title'] = template['title'].replace('{{nazev}}', nazev).replace('<<x>>', image_count_str)
    if 'description' in template:
        product['description'] = template['description'].replace('{{nazev}}', nazev).replace('<<x>>', image_count_str)
    if 'tags' in template:
        # Nahradíme {{nazev}} a <<x>>, a také {{název}} pro jistotu
        tags_str = template['tags']
        tags_str = tags_str.replace('{{nazev}}', nazev).replace('{{název}}', nazev).replace('<<x>>', image_count_str)
        print(f"Před zpracováním tagy: {tags_str}")  # Debug
        product['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        print(f"Po zpracování tagy: {product['tags']}")  # Debug
    if 'price' in template:
        price_str = str(template['price']).replace(',', '.')
        product['price'] = float(price_str)
    if 'quantity' in template:
        product['quantity'] = int(template['quantity'])
    if 'craft_type' in template:
        product['craft_type'] = template['craft_type']
    if 'primary_color' in template:
        product['primary_color'] = template['primary_color']
    if 'secondary_color' in template:
        product['secondary_color'] = template['secondary_color']
    if 'subject' in template:
        product['subject'] = template['subject']
    if 'holiday' in template:
        product['holiday'] = template['holiday']
    if 'occasion' in template:
        product['occasion'] = template['occasion']
    if 'shop_section_id' in template:
        product['shop_section_id'] = template['shop_section_id']

def load_media(product: Dict[str, any], lightroom_watermark_folder: str) -> None:
    nazev = product['nazev']
    pattern = os.path.join(lightroom_watermark_folder, f"*{nazev}*")
    folders = glob.glob(pattern)
    if not folders:
        print(f'Folder not found for product "{nazev}" using pattern {pattern}')
        return
    product_folder = folders[0]
    jpg_images = glob.glob(os.path.join(product_folder, '*.jpg'))
    png_images = glob.glob(os.path.join(product_folder, '*.png'))
    video_paths = glob.glob(os.path.join(product_folder, '*.mp4')) + glob.glob(os.path.join(product_folder, '*.MP4'))
    
    def extract_number(filename):
        match = re.search(r'_(\d+)', os.path.basename(filename))
        return int(match.group(1)) if match else float('inf')
    
    jpg_images.sort(key=extract_number)
    png_images.sort(key=extract_number)
    
    jpg_count = len(jpg_images)
    png_count = len(png_images)
    if jpg_count >= png_count:
        product['image_count'] = jpg_count
        product['images'] = jpg_images
    else:
        product['image_count'] = png_count
        product['images'] = png_images
    
    product['video'] = video_paths[0] if video_paths else None

def load_products(root_folder: str, template_name: str = 'default') -> List[Dict[str, any]]:
    products = []
    templates = load_templates()
    template = templates.get(template_name, templates['default'])
    print(f"Načtená šablona: {template}")  # Debug
    lightroom_folder = os.path.join(root_folder, 'Lightroom')
    lightroom_watermark_folder = os.path.join(root_folder, 'Lightroom Watermark')
    if not os.path.isdir(lightroom_folder):
        print(f"Neexistuje složka: {lightroom_folder}")
        return products
    product_folders = [f.path for f in os.scandir(lightroom_folder) if f.is_dir()]
    for product_folder in product_folders:
        raw_name = os.path.basename(product_folder)
        for suffix in PRODUCT_NAME_SUFFIXES:
            raw_name = raw_name.replace(f" by {suffix}", "")
            raw_name = raw_name.replace(suffix, "")
        nazev = raw_name.strip()
        product = {
            'nazev': nazev,
            'zip_path': None,
            'images': [],
            'video': None,
            'status': 'Připraven',
            'image_count': 0,
            'subject': [],
            'holiday': [],
            'occasion': []
        }
        zip_files = glob.glob(os.path.join(product_folder, '*.zip'))
        if zip_files:
            product['zip_path'] = zip_files[0]
        else:
            print(f'No ZIP file found in {product_folder}, skipping product.')
            continue
        load_media(product, lightroom_watermark_folder)
        generate_content(product, template)
        products.append(product)
    return products

def duplicate_product(product: Dict[str, any]) -> Dict[str, any]:
    return deepcopy(product)

def upload_images(listing_id: int, image_paths: List[str], access_token: str) -> None:
    if MultipartEncoder is None:
        raise RuntimeError("Chybi balicek requests_toolbelt pro upload obrazku.")
    for idx, image_path in enumerate(image_paths):
        with open(image_path, 'rb') as img_file:
            m = MultipartEncoder(fields={
                'image': (os.path.basename(image_path), img_file, 'image/png'),
                'rank': str(idx+1)
            })
            headers = build_headers(access_token, content_type=m.content_type)
            response = requests.post(f'https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}/images',
                                     headers=headers, data=m)
            if response.status_code == 201:
                print(f'Obrázek {image_path} nahrán.')
            else:
                print(f'Chyba při nahrávání obrázku {image_path}: {response.text}')

def upload_digital_file(listing_id: int, file_path: str, access_token: str) -> None:
    if MultipartEncoder is None:
        raise RuntimeError("Chybi balicek requests_toolbelt pro upload souboru.")
    original_name = os.path.basename(file_path)
    safe_name = sanitize_upload_filename(original_name)
    if safe_name != original_name:
        print(f"Upraven nazev ZIP pro upload: {original_name} -> {safe_name}")
    if not is_valid_upload_filename(safe_name):
        raise RuntimeError(f"Neplatny nazev ZIP pro upload: {safe_name}")
    with open(file_path, 'rb') as file_data:
        m = MultipartEncoder(fields={
            'file': (safe_name, file_data, 'application/zip'),
            'name': safe_name
        })
        headers = build_headers(access_token, content_type=m.content_type)
        response = requests.post(f'https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}/files',
                                 headers=headers, data=m)
        if response.status_code == 201:
            print(f'Digitální soubor {file_path} nahrán.')
        else:
            print(f'Chyba při nahrávání digitálního souboru {file_path}: {response.text}')

def upload_video(listing_id: int, video_path: str, access_token: str) -> None:
    if MultipartEncoder is None:
        raise RuntimeError("Chybi balicek requests_toolbelt pro upload videa.")
    video_name = os.path.basename(video_path)
    if not video_name.strip():
        video_name = "video.mp4"
    with open(video_path, 'rb') as video_file:
        m = MultipartEncoder(fields={
            'video': (video_name, video_file, 'video/mp4'),
            'rank': '1',
            'name': video_name
        })
        headers = build_headers(access_token, content_type=m.content_type)
        response = requests.post(
            f'https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}/videos',
            headers=headers, data=m)
        if response.status_code == 201:
            print(f'Video {video_path} nahráno.')
        else:
            print(f'Chyba při nahrávání videa {video_path}: {response.text}')

def update_properties(listing_id: int, access_token: str, product: Dict[str, any]) -> None:
    taxonomy_url = "https://openapi.etsy.com/v3/application/seller-taxonomy/nodes/6844/properties"
    headers = build_headers(access_token)
    try:
        response = requests.get(taxonomy_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        for property_data in data.get("results", []):
            prop_name = property_data.get("name")
            property_id = property_data["property_id"]
            possible_values = property_data.get("possible_values", [])
            property_update_url = f"https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}/properties/{property_id}"

            if prop_name == "Craft type":
                payload = {"property_id": property_id, "value_ids": [], "values": []}
                for value in possible_values:
                    payload["value_ids"].append(value["value_id"])
                    payload["values"].append(value["name"])
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Craft type úspěšně aktualizováno")
                else:
                    print(f"Chyba při aktualizaci Craft type: {put_response.status_code} {put_response.text}")

            elif prop_name == "Primary color":
                selected_value = product.get("primary_color", "Black")
                if not selected_value or selected_value.lower() == "none":
                    continue
                value_ids = []
                values = []
                for value in possible_values:
                    if value["name"].lower() == selected_value.lower():
                        value_ids.append(value["value_id"])
                        values.append(value["name"])
                        break
                if not value_ids:
                    print(f"Nenalezena odpovídající hodnota pro Primary color: {selected_value}")
                    continue
                payload = {"property_id": property_id, "value_ids": value_ids, "values": values}
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Primary color úspěšně aktualizována")
                else:
                    print(f"Chyba při aktualizaci Primary color: {put_response.status_code} {put_response.text}")

            elif prop_name == "Secondary color":
                selected_value = product.get("secondary_color", "Black")
                if not selected_value or selected_value.lower() == "none":
                    continue
                value_ids = []
                values = []
                for value in possible_values:
                    if value["name"].lower() == selected_value.lower():
                        value_ids.append(value["value_id"])
                        values.append(value["name"])
                        break
                if not value_ids:
                    print(f"Nenalezena odpovídající hodnota pro Secondary color: {selected_value}")
                    continue
                payload = {"property_id": property_id, "value_ids": value_ids, "values": values}
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Secondary color úspěšně aktualizována")
                else:
                    print(f"Chyba při aktualizaci Secondary color: {put_response.status_code} {put_response.text}")

            elif prop_name in ("Subject", "Art subject"):
                selected_subjects = product.get("subject", [])
                if not selected_subjects:
                    continue
                value_ids = []
                values = []
                for selected in selected_subjects:
                    for value in possible_values:
                        if value["name"].lower() == selected.lower():
                            value_ids.append(value["value_id"])
                            values.append(value["name"])
                            break
                if not value_ids:
                    print(f"Nenalezena odpovídající hodnota pro Art subject: {selected_subjects}")
                    continue
                payload = {"property_id": property_id, "value_ids": value_ids, "values": values}
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Art subject úspěšně aktualizován")
                else:
                    print(f"Chyba při aktualizaci Art subject: {put_response.status_code} {put_response.text}")

            elif prop_name == "Holiday":
                selected_holidays = product.get("holiday", [])
                if not selected_holidays:
                    continue
                value_ids = []
                values = []
                for selected in selected_holidays:
                    for value in possible_values:
                        if value["name"].lower() == selected.lower():
                            value_ids.append(value["value_id"])
                            values.append(value["name"])
                            break
                if not value_ids:
                    print(f"Nenalezena odpovídající hodnota pro Holiday: {selected_holidays}")
                    continue
                payload = {"property_id": property_id, "value_ids": value_ids, "values": values}
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Holiday úspěšně aktualizován")
                else:
                    print(f"Chyba při aktualizaci Holiday: {put_response.status_code} {put_response.text}")

            elif prop_name == "Occasion":
                selected_occasions = product.get("occasion", [])
                if not selected_occasions:
                    continue
                value_ids = []
                values = []
                for selected in selected_occasions:
                    for value in possible_values:
                        if value["name"].lower() == selected.lower():
                            value_ids.append(value["value_id"])
                            values.append(value["name"])
                            break
                if not value_ids:
                    print(f"Nenalezena odpovídající hodnota pro Occasion: {selected_occasions}")
                    continue
                payload = {"property_id": property_id, "value_ids": value_ids, "values": values}
                put_response = requests.put(property_update_url, headers=headers, json=payload)
                if put_response.status_code == 200:
                    print("Occasion úspěšně aktualizován")
                else:
                    print(f"Chyba při aktualizaci Occasion: {put_response.status_code} {put_response.text}")

    except requests.exceptions.RequestException as e:
        print(f"Došlo k chybě při komunikaci s API: {e}")

def upload_listing(product: Dict[str, any], access_token: str) -> bool:
    headers = build_headers(access_token, content_type='application/x-www-form-urlencoded')
    log_headers_safe(headers, context='create_listing')
    nazev = product.get('nazev', '')
    image_count_str = str(product.get('image_count', 0))

    def replace_placeholders(value: str) -> str:
        """Do-replaces template placeholders before upload."""
        return (value.replace('{{nazev}}', nazev)
                     .replace('{{název}}', nazev)
                     .replace('<<x>>', image_count_str))

    raw_title = product.get('title', '')
    title = trim_title(replace_placeholders(raw_title))
    description = replace_placeholders(product.get('description', ''))
    tags = [replace_placeholders(tag.strip()) for tag in product.get('tags', []) if tag.strip()]
    tags = sanitize_tags(tags)
    print(f"Nahrávám listing s tagy: {tags}")  # Debug výstup
    data = {
        'title': title,
        'description': description,
        'price': str(product.get('price', 10.0)),
        'quantity': product.get('quantity', 999),
        'tags': ', '.join(tags),
        'who_made': 'i_did',
        'when_made': '2020_2025',
        'taxonomy_id': 6844,
        'state': 'draft',
        'type': "download",
    }
    response = requests.post(f'https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings', data=data, headers=headers)
    if response.status_code == 201:
        listing_id = response.json()['listing_id']
        print(f'Listing vytvořen s ID: {listing_id}')
        limited_images = product['images'][:20]
        upload_images(listing_id, limited_images, access_token)
        upload_digital_file(listing_id, product['zip_path'], access_token)
        if product.get('video'):
            upload_video(listing_id, product['video'], access_token)
        update_properties(listing_id, access_token, product)
        return True
    print(f'Chyba při nahrávání listingu: {response.text}')
    return False
