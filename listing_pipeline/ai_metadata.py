import json
import os
import re
import unicodedata
import colorsys
import base64
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from PIL import Image
except ImportError:
    Image = None


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:8b")

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

NEUTRAL_COLORS = {"White", "Gray", "Silver"}

SUBJECT_DEFAULTS = ["Animal", "Flowers", "Landscape & scenery"]

SUBJECT_KEYWORDS = [
    ("animal", "Animal"),
    ("bear", "Animal"),
    ("cat", "Animal"),
    ("dog", "Animal"),
    ("flower", "Flowers"),
    ("floral", "Flowers"),
    ("botanical", "Plants & trees"),
    ("plant", "Plants & trees"),
    ("tree", "Plants & trees"),
    ("portrait", "People & portrait"),
    ("people", "People & portrait"),
    ("pet", "Pet portrait"),
    ("landscape", "Landscape & scenery"),
    ("nature", "Landscape & scenery"),
    ("beach", "Beach & tropical"),
    ("tropical", "Beach & tropical"),
    ("fantasy", "Fantasy & Sci Fi"),
    ("wizard", "Fantasy & Sci Fi"),
    ("space", "Stars & celestial"),
    ("zodiac", "Zodiac"),
    ("comic", "Comics & manga"),
    ("manga", "Comics & manga"),
    ("anime", "Anime & cartoon"),
    ("cartoon", "Anime & cartoon"),
    ("superhero", "Superhero"),
    ("travel", "Travel & transportation"),
    ("car", "Travel & transportation"),
    ("movie", "Movie"),
    ("music", "Music"),
    ("fashion", "Fashion"),
    ("science", "Science & tech"),
    ("tech", "Science & tech"),
    ("sport", "Sports & fitness"),
    ("cowboy", "Western & cowboy"),
    ("nautical", "Nautical"),
    ("military", "Military"),
    ("religious", "Religious"),
]

HOLIDAY_KEYWORDS = [
    ("valentine", "Valentine's Day"),
    ("christmas", "Christmas"),
    ("halloween", "Halloween"),
    ("easter", "Easter"),
    ("thanksgiving", "Thanksgiving"),
    ("hanukkah", "Hanukkah"),
    ("new year", "New Year's"),
    ("mothers day", "Mother's Day"),
    ("fathers day", "Father's Day"),
]

OCCASION_KEYWORDS = [
    ("wedding", "Wedding"),
    ("birthday", "Birthday"),
    ("baby shower", "Baby shower"),
    ("anniversary", "Anniversary"),
    ("graduation", "Graduation"),
    ("engagement", "Engagement"),
    ("bridal", "Bridal shower"),
    ("housewarming", "Housewarming"),
]

COLOR_RGB_MAP = {
    "Beige": (222, 204, 170),
    "Black": (25, 25, 25),
    "Blue": (68, 120, 210),
    "Bronze": (140, 110, 70),
    "Brown": (111, 78, 55),
    "Copper": (184, 115, 51),
    "Gold": (212, 175, 55),
    "Gray": (128, 128, 128),
    "Green": (80, 160, 90),
    "Orange": (240, 140, 45),
    "Pink": (220, 130, 170),
    "Purple": (148, 90, 190),
    "Red": (205, 55, 55),
    "Rose gold": (183, 110, 121),
    "Silver": (180, 180, 185),
    "White": (245, 245, 245),
    "Yellow": (245, 210, 70),
}


def _normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _match_allowed(values: Any, allowed: List[str], limit: Optional[int] = None) -> List[str]:
    normalized_allowed = {_normalize_key(option): option for option in allowed}
    matched: List[str] = []
    seen = set()
    for value in _coerce_list(values):
        option = normalized_allowed.get(_normalize_key(value))
        if not option:
            continue
        if option in seen:
            continue
        seen.add(option)
        matched.append(option)
        if limit is not None and len(matched) >= limit:
            break
    return matched


def _merge_unique(*value_lists: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for values in value_lists:
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged


def _subjects_from_keywords(text: str) -> List[str]:
    matches: List[str] = []
    for keyword, subject in SUBJECT_KEYWORDS:
        if keyword in text and subject not in matches:
            matches.append(subject)
    return matches


def _single_from_keywords(text: str, keyword_map: List[Tuple[str, str]]) -> List[str]:
    for keyword, option in keyword_map:
        if keyword in text:
            return [option]
    return []


def _all_from_keywords(text: str, keyword_map: List[Tuple[str, str]]) -> List[str]:
    values: List[str] = []
    for keyword, option in keyword_map:
        if keyword in text and option not in values:
            values.append(option)
    return values


def _ensure_three_subjects(subjects: List[str], text: str) -> List[str]:
    output = [value for value in subjects if value in SUBJECT_OPTIONS]
    output = _merge_unique(output)

    if len(output) < 3:
        output = _merge_unique(output, _subjects_from_keywords(text))

    if len(output) < 3:
        output = _merge_unique(output, SUBJECT_DEFAULTS)

    if len(output) < 3:
        output = _merge_unique(output, SUBJECT_OPTIONS)

    return output[:3]


def _distance(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _map_rgb_to_color(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    spread = max(rgb) - min(rgb)
    if spread < 12 and max(rgb) > 238:
        return "White"
    if spread < 10 and max(rgb) < 40:
        return "Black"
    if spread < 16:
        if max(rgb) > 170:
            return "Silver"
        return "Gray"

    nearest = min(COLOR_RGB_MAP.items(), key=lambda item: _distance(rgb, item[1]))[0]
    return nearest


def _estimate_background_rgb(edge_pixels: List[Tuple[int, int, int]]) -> Optional[Tuple[int, int, int]]:
    if not edge_pixels:
        return None
    sorted_r = sorted(pixel[0] for pixel in edge_pixels)
    sorted_g = sorted(pixel[1] for pixel in edge_pixels)
    sorted_b = sorted(pixel[2] for pixel in edge_pixels)
    mid = len(edge_pixels) // 2
    return sorted_r[mid], sorted_g[mid], sorted_b[mid]


def _classify_etsy_color(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    h = h * 360.0

    if v <= 0.13:
        return "Black"

    if s <= 0.12:
        if v >= 0.90:
            return "White"
        if v >= 0.75:
            return "Silver"
        return "Gray"

    if 18 <= h < 35 and s > 0.45 and 0.35 <= v <= 0.75:
        return "Copper"
    if 28 <= h < 48 and s > 0.45 and 0.25 <= v <= 0.62:
        return "Bronze"
    if 35 <= h < 63 and s > 0.45 and v >= 0.62:
        return "Gold"
    if 25 <= h < 60 and s < 0.35 and v >= 0.65:
        return "Beige"

    if h >= 350 or h < 18:
        if s < 0.45 and v > 0.65:
            return "Rose gold"
        return "Red"
    if 18 <= h < 45:
        if v < 0.55:
            return "Brown"
        return "Orange"
    if 45 <= h < 70:
        return "Yellow"
    if 70 <= h < 170:
        return "Green"
    if 170 <= h < 260:
        return "Blue"
    if 260 <= h < 320:
        if h >= 295 and s < 0.50 and v > 0.65:
            return "Pink"
        return "Purple"
    if 320 <= h < 350:
        if s < 0.45 and v > 0.60:
            return "Rose gold"
        return "Pink"

    return _map_rgb_to_color(rgb)


def _hue_group(rgb: Tuple[int, int, int]) -> Optional[str]:
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if s < 0.25 or v < 0.20:
        return None
    h = h * 360.0
    if h < 30 or h >= 330:
        return "red"
    if h < 60:
        return "orange"
    if h < 90:
        return "yellow"
    if h < 170:
        return "green"
    if h < 260:
        return "blue"
    return "purple"


def _dominant_rgb_values(image_paths: List[str], max_images: int = 3) -> List[Tuple[int, int, int]]:
    if Image is None:
        return []
    buckets: Counter = Counter()
    for image_path in image_paths[:max_images]:
        if not image_path or not os.path.exists(image_path):
            continue
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGBA")
                img.thumbnail((160, 160))
                width, height = img.size
                data = img.getdata()
                if data is None:
                    continue
                pixels = list(data)  # type: ignore[arg-type]
                edge_pixels: List[Tuple[int, int, int]] = []

                for x in range(width):
                    for y in (0, height - 1):
                        r, g, b, a = pixels[y * width + x]
                        if a >= 30:
                            edge_pixels.append((r, g, b))
                for y in range(height):
                    for x in (0, width - 1):
                        r, g, b, a = pixels[y * width + x]
                        if a >= 30:
                            edge_pixels.append((r, g, b))

                background_rgb = _estimate_background_rgb(edge_pixels)

                for r, g, b, a in pixels:
                    if a < 30:
                        continue
                    if background_rgb and _distance((r, g, b), background_rgb) < 42:
                        continue
                    if r > 248 and g > 248 and b > 248:
                        continue
                    key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
                    buckets[key] += 1
        except Exception:
            continue

    if not buckets:
        for image_path in image_paths[:max_images]:
            if not image_path or not os.path.exists(image_path):
                continue
            try:
                with Image.open(image_path) as img:
                    img = img.convert("RGBA")
                    img.thumbnail((160, 160))
                    data = img.getdata()
                    if data is None:
                        continue
                    for r, g, b, a in data:  # type: ignore[misc]
                        if a < 30:
                            continue
                        if r > 245 and g > 245 and b > 245:
                            continue
                        key = (r // 16 * 16, g // 16 * 16, b // 16 * 16)
                        buckets[key] += 1
            except Exception:
                continue

    if not buckets:
        return []

    top = [bucket for bucket, _ in buckets.most_common(12)]
    dominant: List[Tuple[int, int, int]] = []
    for color in top:
        color_center = (
            min(color[0] + 8, 255),
            min(color[1] + 8, 255),
            min(color[2] + 8, 255),
        )
        if not dominant:
            dominant.append(color_center)
            continue
        if all(_distance(color_center, existing) > 40 for existing in dominant):
            dominant.append(color_center)
        if len(dominant) >= 2:
            break
    return dominant


def _colors_from_text_fallback(text: str) -> List[str]:
    text_key = _normalize_key(text)
    keyword_map = [
        ("black", "Black"),
        ("white", "White"),
        ("gray", "Gray"),
        ("grey", "Gray"),
        ("brown", "Brown"),
        ("beige", "Beige"),
        ("blue", "Blue"),
        ("green", "Green"),
        ("red", "Red"),
        ("pink", "Pink"),
        ("purple", "Purple"),
        ("yellow", "Yellow"),
        ("orange", "Orange"),
        ("gold", "Gold"),
        ("silver", "Silver"),
        ("bronze", "Bronze"),
        ("copper", "Copper"),
    ]
    result: List[str] = []
    for keyword, color in keyword_map:
        if keyword in text_key and color not in result:
            result.append(color)
        if len(result) >= 2:
            break
    return result


def suggest_colors(product: Dict[str, Any]) -> Tuple[str, str]:
    image_paths = product.get("images", []) or []
    color_votes: Counter = Counter()
    hue_votes: Counter = Counter()
    foreground_pixel_count = 0

    if Image is not None:
        for image_path in image_paths[:3]:
            if not image_path or not os.path.exists(image_path):
                continue
            try:
                with Image.open(image_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((220, 220))
                    width, height = img.size
                    data = img.getdata()
                    if data is None:
                        continue
                    pixels = list(data)  # type: ignore[arg-type]

                    edge_pixels: List[Tuple[int, int, int]] = []
                    for x in range(width):
                        edge_pixels.append(pixels[x])
                        edge_pixels.append(pixels[(height - 1) * width + x])
                    for y in range(height):
                        edge_pixels.append(pixels[y * width])
                        edge_pixels.append(pixels[y * width + (width - 1)])

                    background_rgb = _estimate_background_rgb(edge_pixels)

                    for r, g, b in pixels:
                        if r > 244 and g > 244 and b > 244:
                            continue
                        if background_rgb and _distance((r, g, b), background_rgb) < 40:
                            continue

                        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                        if s < 0.10 and v > 0.72:
                            continue
                        if v < 0.08:
                            continue

                        rgb = (r, g, b)
                        color_name = _classify_etsy_color(rgb)
                        if color_name == "White":
                            continue
                        color_votes[color_name] += 1
                        group = _hue_group(rgb)
                        if group:
                            hue_votes[group] += 1
                        foreground_pixel_count += 1
            except Exception:
                continue

    chromatic_total = sum(hue_votes.values())
    if chromatic_total > 0 and foreground_pixel_count > 0:
        dominant_groups = [
            name for name, count in hue_votes.items()
            if (count / chromatic_total) >= 0.12
        ]
        if len(dominant_groups) >= 4 and (chromatic_total / foreground_pixel_count) >= 0.45:
            secondary_pool = [
                (name, count) for name, count in color_votes.items()
                if name not in {"Rainbow", "White"}
            ]
            if secondary_pool:
                secondary_pool.sort(key=lambda item: item[1], reverse=True)
                secondary = secondary_pool[0][0]
            else:
                secondary = "Black"
            return "Rainbow", secondary

    colors = [name for name, _ in color_votes.most_common(6) if name in COLOR_OPTIONS and name != "White"]

    if len(colors) < 2:
        text_blob = " ".join([
            str(product.get("nazev", "")),
            str(product.get("title", "")),
            str(product.get("description", "")),
            ", ".join(product.get("tags", []) or []),
            os.path.basename(str(product.get("zip_path", ""))),
        ])
        for color_name in _colors_from_text_fallback(text_blob):
            if color_name == "White":
                continue
            if color_name not in colors:
                colors.append(color_name)
            if len(colors) >= 2:
                break

    colors = _merge_unique(colors)
    total_votes = sum(color_votes.values())
    non_neutral_votes = {name: count for name, count in color_votes.items() if name not in NEUTRAL_COLORS and name != "White"}
    if non_neutral_votes and total_votes > 0:
        top_non_neutral = max(non_neutral_votes.items(), key=lambda item: item[1])
        if (top_non_neutral[1] / total_votes) >= 0.18 and top_non_neutral[0] not in colors:
            colors.insert(0, top_non_neutral[0])

    non_neutral = [color for color in colors if color not in NEUTRAL_COLORS]

    if non_neutral:
        primary = non_neutral[0]
    elif "Black" in colors:
        primary = "Black"
    elif colors:
        primary = colors[0]
    else:
        primary = "Black"

    secondary_candidates = [
        color for color in colors
        if color != primary and color not in NEUTRAL_COLORS
    ]

    if not secondary_candidates:
        text_blob = " ".join([
            str(product.get("nazev", "")),
            str(product.get("title", "")),
            str(product.get("description", "")),
            ", ".join(product.get("tags", []) or []),
        ])
        text_fallback_colors = [
            color for color in _colors_from_text_fallback(text_blob)
            if color != primary and color not in NEUTRAL_COLORS
        ]
        secondary_candidates = text_fallback_colors

    if secondary_candidates:
        secondary = secondary_candidates[0]
    elif primary != "Black":
        secondary = "Black"
    else:
        secondary = "Brown"

    if primary == secondary:
        secondary = "Black" if primary != "Black" else "Brown"

    return primary, secondary


def _build_prompt(product: Dict[str, Any]) -> str:
    nazev = str(product.get("nazev", ""))
    title = str(product.get("title", ""))
    description = str(product.get("description", ""))
    tags = ", ".join(product.get("tags", []) or [])
    zip_name = os.path.basename(str(product.get("zip_path", "")))

    return (
        "You are an Etsy listing metadata classifier using the provided image and text. "
        "Ignore plain white studio background when choosing colors. "
        "Return strict JSON only with keys subject, holiday, occasion, primary_color, secondary_color, confidence.\n"
        f"Allowed Subject values: {', '.join(SUBJECT_OPTIONS)}\n"
        f"Allowed Holiday values: {', '.join(HOLIDAY_OPTIONS)}\n"
        f"Allowed Occasion values: {', '.join(OCCASION_OPTIONS)}\n"
        f"Allowed Color values: {', '.join(COLOR_OPTIONS)}\n"
        "Rules: subject must contain exactly 3 unique values, "
        "holiday must contain at most 1 value, occasion must contain at most 1 value, "
        "primary_color and secondary_color must be single values from allowed colors, "
        "choose only from allowed lists, no extra keys.\n"
        "If no clear holiday or occasion is visible, return empty arrays for those fields.\n"
        f"Listing name: {nazev}\n"
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Tags: {tags}\n"
        f"Zip filename: {zip_name}\n"
        "Output JSON example: {\"subject\":[],\"holiday\":[],\"occasion\":[],\"primary_color\":\"Black\",\"secondary_color\":\"White\",\"confidence\":0.0}"
    )


def _parse_response_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _parse_response_loose(raw: str) -> Dict[str, Any]:
    text = str(raw or "")
    text_norm = _normalize_key(text)

    def find_allowed(allowed: List[str], limit: Optional[int] = None) -> List[str]:
        values: List[str] = []
        for option in allowed:
            if _normalize_key(option) in text_norm and option not in values:
                values.append(option)
            if limit is not None and len(values) >= limit:
                break
        return values

    confidence = 0.0
    match = re.search(r"confidence[^0-9]*([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    if match:
        try:
            confidence = float(match.group(1))
        except Exception:
            confidence = 0.0

    subject_values = find_allowed(SUBJECT_OPTIONS, limit=3)
    holiday_values = find_allowed(HOLIDAY_OPTIONS, limit=1)
    occasion_values = find_allowed(OCCASION_OPTIONS, limit=1)
    color_values = find_allowed([c for c in COLOR_OPTIONS if c != "Rainbow"], limit=2)

    return {
        "subject": subject_values,
        "holiday": holiday_values,
        "occasion": occasion_values,
        "primary_color": color_values[0] if color_values else "",
        "secondary_color": color_values[1] if len(color_values) > 1 else "",
        "confidence": confidence,
    }


def _encode_image_base64(image_path: str) -> Optional[str]:
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None


def _collect_vision_images(product: Dict[str, Any], max_images: int = 1) -> List[str]:
    encoded_images: List[str] = []
    for image_path in (product.get("images", []) or [])[:max_images]:
        encoded = _encode_image_base64(str(image_path))
        if encoded:
            encoded_images.append(encoded)
    return encoded_images


def _call_ollama(prompt: str, model: str, images: Optional[List[str]] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "think": False,
        },
        "prompt": prompt,
    }
    if images:
        payload["images"] = images
    response = requests.post(OLLAMA_URL, json=payload, timeout=(8, timeout_seconds))
    response.raise_for_status()
    body = response.json()
    raw_response = body.get("response", "") or body.get("thinking", "")
    if not raw_response:
        raise RuntimeError("Ollama nevratila zadny response text.")
    try:
        parsed = _parse_response_json(raw_response)
    except Exception:
        parsed = _parse_response_loose(raw_response)
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama response nema JSON objekt.")
    return parsed


def _heuristic_taxonomy(product: Dict[str, Any]) -> Dict[str, Any]:
    text = _normalize_key(" ".join([
        str(product.get("nazev", "")),
        str(product.get("title", "")),
        str(product.get("description", "")),
        ", ".join(product.get("tags", []) or []),
    ]))

    subjects = _ensure_three_subjects(_subjects_from_keywords(text), text)
    holidays = _single_from_keywords(text, HOLIDAY_KEYWORDS)
    occasions = _single_from_keywords(text, OCCASION_KEYWORDS)

    return {
        "subject": subjects,
        "holiday": holidays[:1],
        "occasion": occasions[:1],
        "confidence": 0.45,
    }


def suggest_taxonomy_fields(product: Dict[str, Any], model: str = OLLAMA_MODEL) -> Dict[str, Any]:
    prompt = _build_prompt(product)
    algo_primary, algo_secondary = suggest_colors(product)
    parsed: Dict[str, Any]
    vision_images = _collect_vision_images(product, max_images=1)
    try:
        parsed = _call_ollama(prompt, model=model, images=vision_images)
        source = "llm"
    except Exception as exc:
        parsed = _heuristic_taxonomy(product)
        parsed["error"] = str(exc)
        source = "heuristic"

    text_for_completion = _normalize_key(" ".join([
        str(product.get("nazev", "")),
        str(product.get("title", "")),
        str(product.get("description", "")),
        ", ".join(product.get("tags", []) or []),
    ]))

    heuristic = _heuristic_taxonomy(product)
    holiday_signal = _all_from_keywords(text_for_completion, HOLIDAY_KEYWORDS)

    llm_subject = _match_allowed(parsed.get("subject", []), SUBJECT_OPTIONS, limit=3)
    llm_holiday = _match_allowed(parsed.get("holiday", []), HOLIDAY_OPTIONS, limit=1)
    llm_occasion = _match_allowed(parsed.get("occasion", []), OCCASION_OPTIONS, limit=1)
    llm_primary = _match_allowed(parsed.get("primary_color", []), COLOR_OPTIONS, limit=1)
    llm_secondary = _match_allowed(parsed.get("secondary_color", []), COLOR_OPTIONS, limit=1)

    subject_values = _ensure_three_subjects(_merge_unique(llm_subject, heuristic.get("subject", [])), text_for_completion)
    if holiday_signal:
        holiday_values = _merge_unique(holiday_signal, llm_holiday, heuristic.get("holiday", []))[:1]
    else:
        holiday_values = []
    occasion_values = _merge_unique(llm_occasion, heuristic.get("occasion", []))[:1]

    primary_color = llm_primary[0] if llm_primary else algo_primary
    secondary_color = llm_secondary[0] if llm_secondary else algo_secondary

    if algo_primary == "Rainbow":
        primary_color = "Rainbow"
        if secondary_color in {"", "Rainbow", "White"}:
            secondary_color = algo_secondary

    if primary_color in NEUTRAL_COLORS and algo_primary not in NEUTRAL_COLORS and algo_primary != "White":
        primary_color = algo_primary

    if primary_color == "White" and algo_primary != "White":
        primary_color = algo_primary
    if secondary_color == "White" and primary_color != "White" and algo_secondary != "White":
        secondary_color = algo_secondary
    if secondary_color == primary_color:
        secondary_color = algo_secondary if algo_secondary != primary_color else ("Black" if primary_color != "Black" else "Gray")

    confidence_value = parsed.get("confidence", heuristic.get("confidence", 0.0))
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "subject": subject_values,
        "holiday": holiday_values,
        "occasion": occasion_values,
        "primary_color": primary_color,
        "secondary_color": secondary_color,
        "confidence": max(0.0, min(confidence, 1.0)),
        "source": source,
        "error": parsed.get("error", ""),
    }


def enrich_product_metadata(product: Dict[str, Any], model: str = OLLAMA_MODEL) -> Dict[str, Any]:
    taxonomy = suggest_taxonomy_fields(product, model=model)
    status = "ok" if taxonomy.get("source") == "llm" else "fallback"

    return {
        "primary_color": taxonomy.get("primary_color", "Black"),
        "secondary_color": taxonomy.get("secondary_color", "Gray"),
        "subject": taxonomy.get("subject", []),
        "holiday": taxonomy.get("holiday", []),
        "occasion": taxonomy.get("occasion", []),
        "ai_confidence": taxonomy.get("confidence", 0.0),
        "ai_model": model,
        "ai_status": status,
        "ai_error": taxonomy.get("error", ""),
        "ai_timestamp": datetime.utcnow().isoformat() + "Z",
    }
