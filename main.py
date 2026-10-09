import os
import io
import re
import requests
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
import sys
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from typing import List, Dict, Any
from supabase import create_client
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from datetime import datetime
import traceback

# ── Register TrueType Fonts for Unicode (₹ Rupee Symbol) ────────────
FONTS_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts")
DEJAVU_REG = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
DEJAVU_BOLD = os.path.join(FONTS_DIR, "DejaVuSans-Bold.ttf")
DEJAVU_OBL = os.path.join(FONTS_DIR, "DejaVuSans-Oblique.ttf")
DEJAVU_BOLDOBL = os.path.join(FONTS_DIR, "DejaVuSans-BoldOblique.ttf")

PDF_FONT_NORMAL = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"

if os.path.exists(DEJAVU_REG):
    pdfmetrics.registerFont(TTFont("DejaVuSans", DEJAVU_REG))
    PDF_FONT_NORMAL = "DejaVuSans"

if os.path.exists(DEJAVU_BOLD):
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", DEJAVU_BOLD))
    PDF_FONT_BOLD = "DejaVuSans-Bold"

if os.path.exists(DEJAVU_OBL):
    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", DEJAVU_OBL))

if os.path.exists(DEJAVU_BOLDOBL):
    pdfmetrics.registerFont(TTFont("DejaVuSans-BoldOblique", DEJAVU_BOLDOBL))

if os.path.exists(DEJAVU_REG) and os.path.exists(DEJAVU_BOLD):
    registerFontFamily(
        "DejaVuSans",
        normal="DejaVuSans",
        bold="DejaVuSans-Bold",
        italic="DejaVuSans-Oblique" if os.path.exists(DEJAVU_OBL) else "DejaVuSans",
        boldItalic="DejaVuSans-BoldOblique" if os.path.exists(DEJAVU_BOLDOBL) else "DejaVuSans-Bold"
    )

load_dotenv()

app = FastAPI(title="Savoury & Sweet Co.")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    print("Supabase configuration missing: SUPABASE_URL and/or SUPABASE_KEY not set.", file=sys.stderr)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── OpenAI / Whisper (optional) ─────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").lower()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MODEL = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)

# ── System Prompt ────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the AI Voice Assistant for 'Savoury & Sweet Co.', an artisanal bakery.
Keep your responses short (under 2 sentences), friendly, and conversational because they will be spoken out loud.
Do not use emojis in your response.

Menu:
Savoury – Indian Snacks:
- Samosa: ₹20
- Vada Pav: ₹16
- Aloo Tikki: ₹40
- Kachori: ₹25
- Veg Puff: ₹40
- Paneer Puff: ₹50
Savoury – Sandwiches & Mains:
- Masala Sandwich: ₹70
- Veg Sandwich: ₹60
- Cheese Sandwich: ₹80
- Cheesy Garlic Bread: ₹150
- Alfredo Spaghetti: ₹250
Sweet – Cakes:
- Chocolate Cake: ₹500
- Vanilla Cake: ₹450
- Butterscotch Cake: ₹350
- Black Forest Cake: ₹550
- Red Velvet Cake: ₹600
Sweet – Bakes & Snacks:
- Butter Croissant: ₹150
- Chocolate Brownie: ₹90
- Cupcake: ₹60
- Chocolate Cupcake: ₹70
- Blueberry Muffin: ₹80
- Muffin: ₹70
- Choco Chip Cookies: ₹60
- Cookies: ₹50
- Donut: ₹50
- Chocolate Donut: ₹60
Beverages:
- Cold Coffee: ₹100
- Chocolate Shake: ₹120
- Mango Shake: ₹110

Store Hours:
- Monday-Friday: 10 AM to 9 PM
- Saturday-Sunday: 9 AM to 7 PM

Important Rules:
Whenever the customer asks to add an item, ALWAYS mention the exact menu item name.
Example:
"I have added 2 Chocolate Cake and 1 Cheesy Garlic Bread to your basket."
Never say "I've added it" or "Done".

Response Format:
Would you like to add anything else, modify your order, or should I place your order?

Reply yes to confirm.

ORDER FLOW:
1. When the customer asks to add items:
   - Add the requested items.
   - Tell the total current basket cost.
   - DO NOT confirm the order.
   - ALWAYS ask :
     "Would you like to add anything else, remove or modify any item, or should I place your order?
      If you're ready, simply reply 'yes' or 'place order'." 

2. ONLY when the customer replies:
   - yes
   - place order
   - confirm
   - proceed
   then end your response with exactly:
   ORDER CONFIRMED

3. Never output ORDER CONFIRMED before the customer confirms.
Do not change this wording.
"""

sessions: Dict[str, List[str]] = {}
pending_confirmation: Dict[str, bool] = {}
waiting_for_name: Dict[str, bool] = {}
customer_names: Dict[str, str] = {}
# Store tentative name awaiting confirmation
name_confirmation_pending: Dict[str, str] = {}

# ── Semantic intent classifier ───────────────────────────────────────────────
# Returned labels: CONFIRM_ORDER | NEGATIVE | OTHER | UNCERTAIN
_INTENT_SYSTEM = (
    "You are an intent classifier for a bakery ordering chatbot. "
    "Classify the customer's message into exactly one label:\n"
    "  CONFIRM_ORDER – the customer wants to place / confirm / proceed with their order "
    "(e.g. 'yes', 'go ahead', 'please order', 'I'm ready', 'proceed', 'confirm', "
    "'that's all, place it', 'yes please', 'I want to place the order').\n"
    "  NEGATIVE – the customer declines, e.g. 'no', 'not yet', 'cancel', 'wait'.\n"
    "  OTHER – anything else (modifying items, asking questions, giving their name, etc.).\n"
    "  UNCERTAIN – you genuinely cannot tell.\n"
    "Reply with only the label, nothing else."
)


def classify_order_intent(message: str) -> str:
    """
    Returns 'CONFIRM_ORDER', 'NEGATIVE', 'OTHER', or 'UNCERTAIN'.
    Falls back to 'UNCERTAIN' on any error so the caller can ask for clarification.
    """
    # Fast deterministic guards to save an LLM round-trip.
    normalized = re.sub(r"[^a-z\s]", "", message.lower()).strip()
    words = normalized.split()

    _FAST_NEGATIVE = {"no", "n", "nope", "nah", "nahi", "cancel", "wait", "stop"}
    if words and all(w in _FAST_NEGATIVE for w in words):
        return "NEGATIVE"

    # Single-word or short obvious affirmatives
    _FAST_AFFIRM = {
        "yes", "y", "yeah", "yep", "yup", "sure", "okay", "ok", "haan",
        "ha", "proceed", "confirm",
    }
    if words and all(w in _FAST_AFFIRM for w in words):
        return "CONFIRM_ORDER"

    # Keyword shortcuts that don't need the LLM
    _CONFIRM_PHRASES = (
        "place order", "place my order", "go ahead", "ready to order",
        "want to place", "place the order", "please order","yes please",
    )
    if any(p in normalized for p in _CONFIRM_PHRASES):
        return "CONFIRM_ORDER"

    # Fast deterministic negative phrases
    _NEGATIVE_PHRASES = (
        "not yet", "no thanks", "dont place", "do not place", "no not yet", "cancel my order", "dont order"
    )
    if any(p in normalized for p in _NEGATIVE_PHRASES):
        return "NEGATIVE"

    # Ask the LLM for anything ambiguous
    if not GROQ_API_KEY:
        return "UNCERTAIN"

    try:
        client = Groq(api_key=GROQ_API_KEY)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=10,
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM},
                {"role": "user", "content": message},
            ],
        )
        label = completion.choices[0].message.content.strip().upper()
        if label in {"CONFIRM_ORDER", "NEGATIVE", "OTHER", "UNCERTAIN"}:
            return label
        return "UNCERTAIN"
    except Exception as exc:
        print(f"[INTENT] classifier error: {exc}")
        return "UNCERTAIN"

class ChatRequest(BaseModel):
    message: str
    cart: List[Dict[str, Any]] = []
    session_id: str = "web_user_123"

MENU = {
    # Savoury – Indian Snacks
    "Samosa": 20,
    "Vada Pav": 16,
    "Aloo Tikki": 40,
    "Kachori": 25,
    "Veg Puff": 40,
    "Paneer Puff": 50,
    # Savoury – Sandwiches
    "Masala Sandwich": 70,
    "Veg Sandwich": 60,
    "Cheese Sandwich": 80,
    "Cheesy Garlic Bread": 150,
    "Alfredo Spaghetti": 250,
    # Sweet – Cakes
    "Chocolate Cake": 500,
    "Vanilla Cake": 450,
    "Butterscotch Cake": 350,
    "Black Forest Cake": 550,
    "Red Velvet Cake": 600,
    # Sweet – Bite-Sized Bakes
    "Butter Croissant": 150,
    "Chocolate Brownie": 90,
    "Cupcake": 60,
    "Chocolate Cupcake": 70,
    "Blueberry Muffin": 80,
    "Muffin": 70,
    "Choco Chip Cookies": 60,
    "Cookies": 50,
    "Donut": 50,
    "Chocolate Donut": 60,
    # Beverages
    "Cold Coffee": 100,
    "Chocolate Shake": 120,
    "Mango Shake": 110,
}

NUMBER_WORDS = {
    "one": 1, "a": 1, "an": 1, "single": 1, "another": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10
}

ALIASES = [
    ("black forest cake", "Black Forest Cake"),
    ("black forest cakes", "Black Forest Cake"),
    ("black forest", "Black Forest Cake"),
    ("red velvet cake", "Red Velvet Cake"),
    ("red velvet cakes", "Red Velvet Cake"),
    ("red velvet", "Red Velvet Cake"),
    ("butterscotch cake", "Butterscotch Cake"),
    ("butterscotch cakes", "Butterscotch Cake"),
    ("butterscotch", "Butterscotch Cake"),
    ("chocolate cake", "Chocolate Cake"),
    ("chocolate cakes", "Chocolate Cake"),
    ("vanilla cake", "Vanilla Cake"),
    ("vanilla cakes", "Vanilla Cake"),
    ("cheesy garlic bread", "Cheesy Garlic Bread"),
    ("garlic bread", "Cheesy Garlic Bread"),
    ("alfredo spaghetti", "Alfredo Spaghetti"),
    ("alfredo", "Alfredo Spaghetti"),
    ("spaghetti", "Alfredo Spaghetti"),
    ("chocolate brownie", "Chocolate Brownie"),
    ("chocolate brownies", "Chocolate Brownie"),
    ("brownies", "Chocolate Brownie"),
    ("brownie", "Chocolate Brownie"),
    ("chocolate cupcake", "Chocolate Cupcake"),
    ("chocolate cupcakes", "Chocolate Cupcake"),
    ("chocolate donut", "Chocolate Donut"),
    ("chocolate donuts", "Chocolate Donut"),
    ("chocolate shake", "Chocolate Shake"),
    ("chocolate shakes", "Chocolate Shake"),
    ("choco chip cookies", "Choco Chip Cookies"),
    ("choco chip cookie", "Choco Chip Cookies"),
    ("choco chip", "Choco Chip Cookies"),
    ("butter croissant", "Butter Croissant"),
    ("butter croissants", "Butter Croissant"),
    ("croissants", "Butter Croissant"),
    ("croissant", "Butter Croissant"),
    ("blueberry muffin", "Blueberry Muffin"),
    ("blueberry muffins", "Blueberry Muffin"),
    ("masala sandwich", "Masala Sandwich"),
    ("masala sandwiches", "Masala Sandwich"),
    ("cheese sandwich", "Cheese Sandwich"),
    ("cheese sandwiches", "Cheese Sandwich"),
    ("veg sandwich", "Veg Sandwich"),
    ("veg sandwiches", "Veg Sandwich"),
    ("vada pavs", "Vada Pav"),
    ("vada pav", "Vada Pav"),
    ("vada", "Vada Pav"),
    ("aloo tikki", "Aloo Tikki"),
    ("paneer puff", "Paneer Puff"),
    ("paneer puffs", "Paneer Puff"),
    ("veg puff", "Veg Puff"),
    ("veg puffs", "Veg Puff"),
    ("cold coffee", "Cold Coffee"),
    ("coffee", "Cold Coffee"),
    ("mango shake", "Mango Shake"),
    ("mango shakes", "Mango Shake"),
    ("samosas", "Samosa"),
    ("samosa", "Samosa"),
    ("kachoris", "Kachori"),
    ("kachori", "Kachori"),
    ("cupcakes", "Cupcake"),
    ("cupcake", "Cupcake"),
    ("muffins", "Muffin"),
    ("muffin", "Muffin"),
    ("cookies", "Cookies"),
    ("cookie", "Cookies"),
    ("donuts", "Donut"),
    ("donut", "Donut"),
    # Veg Puff — "vegetable" spelling variants (vegetable puff is common typed/spoken variant)
    ("vegetable puff", "Veg Puff"),
    ("vegetable puffs", "Veg Puff"),
    # Veg Sandwich — "vegetable" spelling variants
    ("vegetable sandwich", "Veg Sandwich"),
    ("vegetable sandwiches", "Veg Sandwich"),
    # Paneer Puff — English description variant
    ("cottage cheese puff", "Paneer Puff"),
]

# ---------------------------------------------------------------------------
# STT_CORRECTIONS — browser/Whisper misrecognition corrections.
# Applied to the raw transcript BEFORE alias/menu matching.
#
# Rules:
#   - Every corrected value must resolve via ALIASES to an existing MENU item.
#   - Corrections are whole-word only (no substring replacement).
#   - Add entries only for misrecognitions confirmed in production console logs.
# ---------------------------------------------------------------------------
STT_CORRECTIONS = {
    # Veg Puff — en-IN Browser STT misrecognitions
    "veg path":      "veg puff",
    "bag puff":      "veg puff",
    "beg puff":      "veg puff",
    "veg buff":      "veg puff",
    "beck puff":     "veg puff",
    "veg puf":       "veg puff",
    # Veg Sandwich — en-IN Browser STT misrecognitions
    "big sandwich":  "veg sandwich",
    "bed sandwich":  "veg sandwich",
    "bag sandwich":  "veg sandwich",
    # Aloo Tikki — common en-IN spelling/pronunciation variants
    "alu tikki":     "aloo tikki",
    "aloo tiki":     "aloo tikki",
    "alu tiki":      "aloo tikki",
    # Vada Pav
    "wada pav":      "vada pav",
    "wada paw":      "vada pav",
    "vada paw":      "vada pav",
    # Kachori
    "kachodi":       "kachori",
    # Paneer Puff
    "panir puff":    "paneer puff",
    "panner puff":   "paneer puff",
}

# Frontend-only threshold (documented here for reference).
# Browser STT confidence values below this are logged as low-confidence
# warnings in the frontend onresult handler.
STT_LOW_CONFIDENCE_THRESHOLD = 0.6


def apply_stt_corrections(text: str) -> str:
    """Apply whole-word STT misrecognition corrections before alias matching."""
    result = text
    for wrong, correct in STT_CORRECTIONS.items():
        result = re.sub(
            rf"\b{re.escape(wrong)}\b",
            correct,
            result,
            flags=re.IGNORECASE,
        )
    if result != text:
        print(f"[STT-CORRECTION] '{text}' → '{result}'")
    return result


def find_menu_item(text):
    text = apply_stt_corrections(text)
    t_lower = text.lower()
    for alias, official in ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", t_lower):
            return official
    for item in MENU:
        if item.lower() in t_lower:
            return item
    return None


def extract_number(text):
    text_lower = text.lower()
    match = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an|single|another)\b", text_lower)
    if match:
        val = match.group(1)
        if val.isdigit():
            return int(val)
        return NUMBER_WORDS.get(val, 1)
    return None

def parse_cart_intent(user_text, cart_list):
    text = apply_stt_corrections(user_text).lower().strip()
    actions = []

    # 1. Clear cart
    if any(k in text for k in ["clear cart", "empty cart", "clear basket", "empty basket", "remove everything"]):
        return [{"action": "clear_cart"}]

    # 2. Check REPLACE INTENT
    replace_match = re.search(r"\b(replace|swap|change)\b", text)
    if replace_match:
        parts = re.split(r"\b(with|to|for)\b", text)
        old_item = None
        new_item = None

        if len(parts) >= 3:
            first_part = parts[0]
            second_part = "".join(parts[2:])
            old_item = find_menu_item(first_part)
            new_item = find_menu_item(second_part)

        if not new_item:
            new_item = find_menu_item(text)

        if new_item:
            if not old_item and cart_list:
                old_item = cart_list[-1]["name"]

            explicit_qty = extract_number(text)
            old_qty = 1
            if old_item and cart_list:
                existing_old = next((i for i in cart_list if i["name"] == old_item), None)
                if existing_old:
                    old_qty = existing_old["quantity"]

            final_qty = explicit_qty if explicit_qty is not None else old_qty

            if old_item and old_item != new_item:
                return [{
                    "action": "replace_item",
                    "old_item": old_item,
                    "new_item": new_item,
                    "quantity": final_qty,
                    "price": MENU[new_item]
                }]
            elif not old_item:
                return [{
                    "action": "set_quantity",
                    "item": new_item,
                    "price": MENU[new_item],
                    "quantity": final_qty
                }]

    # 3. MULTI-ITEM / SINGLE-ITEM ADD, SET, REDUCE, REMOVE
    #
    # IMPORTANT:
    # Do not split only on commas/and/plus.
    # Voice input can be:
    # "black forest cake aloo tikki Alfredo Spaghetti"
    #
    # Instead, scan the complete sentence for every known MENU/ALIAS item.

    is_global_set = bool(re.match(r"^(make|set)\b", text))

    # Build all possible item names from aliases + MENU.
    # Longest phrases must be checked first so that:
    # "chocolate cupcake" is detected before "cupcake"
    # "black forest cake" before "cake", etc.
    candidates = []

    for alias, official in ALIASES:
        candidates.append((alias.lower(), official))

    for item in MENU:
        candidates.append((item.lower(), item))

    # Remove duplicates and sort longest first
    candidates = list(set(candidates))
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    matches = []

    # Find every menu item anywhere in the user's sentence
    for alias, official in candidates:
        pattern = rf"\b{re.escape(alias)}\b"

        for match in re.finditer(pattern, text):
            matches.append({
                "start": match.start(),
                "end": match.end(),
                "item": official
            })

    # Sort by position in the sentence
    matches.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))

    # Remove overlapping matches.
    # Example:
    # "chocolate cupcake"
    # should not become both Chocolate Cupcake + Cupcake.
    filtered_matches = []
    occupied_until = -1

    for match in matches:
        if match["start"] >= occupied_until:
            filtered_matches.append(match)
            occupied_until = match["end"]

    # Extract quantity immediately before each detected item.
    number_pattern = (
        r"(?:\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"a|an|single|another)\b)"
    )

    for idx, match in enumerate(filtered_matches):

        # Text immediately before this item
        previous_end = (
            filtered_matches[idx - 1]["end"]
            if idx > 0
            else 0
        )

        prefix = text[previous_end:match["start"]].strip()

        # Look for quantity near the item.
        # This handles:
        # "two brownies"
        # "two chocolate brownies"
        # "one aloo tikki"
        # "a mango shake"
        qty_match = re.search(
            rf"{number_pattern}\s*$",
            prefix
        )

        if qty_match:
            value = qty_match.group(1)

            if value.isdigit():
                qty = int(value)
            else:
                qty = NUMBER_WORDS.get(value, 1)
        else:
            qty = 1

        # Prevent invalid quantities
        qty = max(1, qty)

        # Text around this item, used to determine the action
        segment_start = (
            filtered_matches[idx - 1]["end"]
            if idx > 0
            else 0
        )

        segment_end = (
            filtered_matches[idx + 1]["start"]
            if idx + 1 < len(filtered_matches)
            else len(text)
        )

        segment = text[segment_start:segment_end].strip()

        item = match["item"]

        # REMOVE
        if any(k in segment for k in [
            "remove",
            "delete",
            "drop",
            "cancel"
        ]):
            if any(k in segment for k in [
                "one",
                "1",
                "one more"
            ]):
                actions.append({
                    "action": "reduce_quantity",
                    "item": item,
                    "quantity": qty
                })
            else:
                actions.append({
                    "action": "remove_item",
                    "item": item
                })

        # REDUCE
        elif any(k in segment for k in [
            "reduce",
            "decrease",
            "minus"
        ]):
            actions.append({
                "action": "reduce_quantity",
                "item": item,
                "quantity": qty
            })

        # SET
        elif (
            any(k in segment for k in [
                "make",
                "set",
                "only"
            ])
            or is_global_set
        ):
            actions.append({
                "action": "set_quantity",
                "item": item,
                "price": MENU[item],
                "quantity": qty
            })

        # ADD
        else:
            actions.append({
                "action": "add_quantity",
                "item": item,
                "price": MENU[item],
                "quantity": qty
            })

    if actions:
        return actions

    # Fallback for commands referring to the last item
    fallback_item = cart_list[-1]["name"] if cart_list else None

    if fallback_item:
        num = extract_number(text)
        qty = num if num is not None else 1

        if any(k in text for k in [
            "make",
            "set",
            "only"
        ]):
            return [{
                "action": "set_quantity",
                "item": fallback_item,
                "price": MENU[fallback_item],
                "quantity": qty
            }]

        elif any(k in text for k in [
            "reduce",
            "decrease",
            "remove one",
            "minus"
        ]):
            return [{
                "action": "reduce_quantity",
                "item": fallback_item,
                "quantity": qty
            }]

        elif any(k in text for k in [
            "add",
            "more",
            "another"
        ]):
            return [{
                "action": "add_quantity",
                "item": fallback_item,
                "price": MENU[fallback_item],
                "quantity": qty
            }]

    return []
def format_action_list(phrases):
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f" and {phrases[-1]}"

def build_cart_response(actions):
    if not actions:
        return ""

    if len(actions) == 1 and actions[0]["action"] == "clear_cart":
        return "Your basket has been cleared. Would you like to start a new order?"

    act_types = set(a["action"] for a in actions)

    if act_types == {"add_quantity"}:
        items = [f"{a['quantity']} {a['item']}" for a in actions]
        main_sentence = f"Added {format_action_list(items)} to your basket."
    elif act_types == {"set_quantity"}:
        if len(actions) == 1:
            main_sentence = f"Set {actions[0]['item']} quantity to {actions[0]['quantity']} in your basket."
        else:
            items = [f"{a['item']} to {a['quantity']}" for a in actions]
            main_sentence = f"Set {format_action_list(items)} in your basket."
    elif act_types == {"reduce_quantity"}:
        if len(actions) == 1:
            main_sentence = f"Reduced {actions[0]['item']} by {actions[0]['quantity']}."
        else:
            items = [f"{a['item']} by {a['quantity']}" for a in actions]
            main_sentence = f"Reduced {format_action_list(items)} in your basket."
    elif act_types == {"remove_item"}:
        items = [a["item"] for a in actions]
        main_sentence = f"Removed {format_action_list(items)} from your basket."
    elif act_types == {"replace_item"}:
        a = actions[0]
        qty_str = f"{a['quantity']} " if a.get("quantity", 1) > 1 else ""
        main_sentence = f"Replaced {a['old_item']} with {qty_str}{a['new_item']} in your basket."
    else:
        # Mixed actions
        phrases = []
        for a in actions:
            at = a["action"]
            if at == "add_quantity":
                phrases.append(f"added {a['quantity']} {a['item']}")
            elif at == "set_quantity":
                phrases.append(f"set {a['item']} to {a['quantity']}")
            elif at == "reduce_quantity":
                phrases.append(f"reduced {a['item']} by {a['quantity']}")
            elif at == "remove_item":
                phrases.append(f"removed {a['item']}")
            elif at == "replace_item":
                qty_str = f"{a['quantity']} " if a.get("quantity", 1) > 1 else ""
                phrases.append(f"replaced {a['old_item']} with {qty_str}{a['new_item']}")

        joined = format_action_list(phrases)
        main_sentence = joined[0].upper() + joined[1:] + " in your basket."

    follow_up = " Would you like to add anything else, remove or modify any item, or should I place your order? Reply yes to confirm."
    return main_sentence + follow_up

def get_ai_response(session_id: str, user_text: str, cart_data: str = "Empty") -> str:
    """Supports both Ollama and Groq."""
    if session_id not in sessions:
        sessions[session_id] = []
    sessions[session_id].append(f"Customer: {user_text}")
    history = "\n".join(sessions[session_id][-6:])
    prompt = f"""
{SYSTEM_PROMPT}
Current Cart:
{cart_data}
Conversation History:
{history}
AI Assistant:
"""
    try:
        # ---------------- OLLAMA ----------------
        if AI_PROVIDER == "ollama":
            print("=" * 50)
            print("Using Ollama...")
            print("=" * 50)
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()
            ai_reply = response.json()["response"].strip()

        # ---------------- GROQ ----------------
        else:
            print("=" * 50)
            print("Using Groq...")
            print("=" * 50)
            client = Groq(api_key=GROQ_API_KEY)
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0.4,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content":
                        f"Current Cart:\n{cart_data}\n\nConversation:\n{history}"
                    }
                ]
            )
            ai_reply = completion.choices[0].message.content.strip()
        sessions[session_id].append(
            f"AI Assistant: {ai_reply}"
        )
        print(ai_reply)
        return ai_reply
    except requests.exceptions.ConnectionError:
        return "Ollama is not running. Please start it using 'ollama serve'."
    except requests.exceptions.Timeout:
        return "The AI model timed out."
    except Exception as e:
        print(e)
        return f"AI Error: {str(e)}"

class OrderRequest(BaseModel):
    customer: str
    items: list
# ════════════════════════════════════════════════════════════════════
#  WEB UI ENDPOINTS
# ════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():

    if AI_PROVIDER == "groq":
        if GROQ_API_KEY:
            return JSONResponse(
                content={
                    "provider": "Groq",
                    "status": "running",
                    "model": GROQ_MODEL
                }
            )
        return JSONResponse(
            content={
                "provider": "Groq",
                "status": "API key missing"
            },
            status_code=503
        )

    # Ollama health check
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]

        return JSONResponse(
            content={
                "provider": "Ollama",
                "status": "running",
                "model": OLLAMA_MODEL,
                "available_models": models
            }
        )

    except Exception:
        return JSONResponse(
            content={
                "provider": "Ollama",
                "status": "not running"
            },
            status_code=503
        )

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )



@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or "web_user_123"
    message = request.message.strip()
    message_lower = message.lower()

    if not request.cart:
        cart_str = "Empty"
    else:
        cart_str = ", ".join(
            f"{i['quantity']}x {i['name']}"
            for i in request.cart
        )

    # ── Step 1: Deterministic cart-intent parser ─────────────────────────────
    # Runs first so cart modifications never reach the intent classifier.
    intent_actions = parse_cart_intent(message, request.cart)

    if intent_actions:
        pending_confirmation.pop(session_id, None)
        waiting_for_name.pop(session_id, None)
        name_confirmation_pending.pop(session_id, None)

        if not (
            len(intent_actions) == 1
            and intent_actions[0].get("action") == "clear_cart"
        ):
            pending_confirmation[session_id] = True

        return {
            "response": build_cart_response(intent_actions),
            "actions": intent_actions,
        }

    # ── Step 2: Name-confirmation state (highest priority after cart ops) ────
    # Interpret yes / no as confirmation of the pending tentative name.
    # Ambiguous replies re-prompt without losing the tentative name.
    if name_confirmation_pending.get(session_id):
        tentative = name_confirmation_pending[session_id]

        normalized = re.sub(r"[^a-zA-Z\s]", "", message_lower).strip()
        words = normalized.split()

        _NAME_YES = {
            "yes", "y", "yeah", "yep", "yup",
            "sure", "correct", "right", "okay", "ok", "haan", "ha",
        }
        _NAME_NO = {
            "no", "n", "nope", "nah", "wrong", "incorrect",
        }

        if words and all(w in _NAME_YES for w in words):
            # Confirmed – pop state and emit the place_order action once.
            name_confirmation_pending.pop(session_id)
            cust_name = tentative
            customer_names[session_id] = cust_name

            return {
                "response": (
                    f"Thank you {cust_name}! "
                    "Your order has been confirmed."
                ),
                "actions": [{"action": "place_order", "customer": cust_name}],
            }

        if words and all(w in _NAME_NO for w in words):
            # Rejected – stay in name-collection mode.
            name_confirmation_pending.pop(session_id)
            waiting_for_name[session_id] = True

            return {
                "response": "No problem. Please tell me your name again.",
                "actions": [],
            }

        # Ambiguous (e.g. customer typed something that is neither yes nor no) –
        # preserve the pending name and re-ask rather than silently accepting.
        # (name_confirmation_pending[session_id] is left intact.)
        return {
            "response": (
                f'Just to confirm – is your name "{tentative}"? '
                "Please reply yes or no."
            ),
            "actions": [],
        }

    # ── Step 3: Name-collection state ───────────────────────────────────────
    # Treat the message as a name unless it is a cancel command.
    if waiting_for_name.get(session_id):
        waiting_for_name.pop(session_id)

        _CANCEL_WORDS = {"cancel", "stop", "quit", "exit", "no"}
        normalized_msg = re.sub(r"[^a-z\s]", "", message_lower).strip()
        if normalized_msg in _CANCEL_WORDS:
            return {
                "response": (
                    "Order cancelled. Let me know if you'd like to start again."
                ),
                "actions": [],
            }

        name_match = re.search(
            r"(?:my name is|i am|i'm|this is|name is)\s+(.+)",
            message,
            re.IGNORECASE,
        )
        tentative = name_match.group(1).strip() if name_match else message.strip()
        tentative = tentative or "Guest Customer"

        name_confirmation_pending[session_id] = tentative

        return {
            "response": f'I heard your name as "{tentative}". Is that correct?',
            "actions": [],
        }

    # ── Step 4: Pending-confirmation state ──────────────────────────────────
    # A cart-item action was just processed; the AI asked if the customer is ready.
    # Use semantic classifier so paraphrases ('go ahead', 'I'm ready', …) work.
    _cached_intent: str = ""  # reused in step 5 to avoid a double LLM call

    if pending_confirmation.get(session_id):
        if not request.cart:
            # Cart was cleared externally; abandon confirmation flow.
            pending_confirmation.pop(session_id)
        else:
            _cached_intent = classify_order_intent(message)

            if _cached_intent == "CONFIRM_ORDER":
                pending_confirmation.pop(session_id)
                waiting_for_name[session_id] = True

                return {
                    "response": (
                        "Great! Before I place your order, "
                        "may I know your name?"
                    ),
                    "actions": [],
                }

            if _cached_intent == "NEGATIVE":
                pending_confirmation.pop(session_id)

                return {
                    "response": "No problem. What would you like to add or change?",
                    "actions": [],
                }

            if _cached_intent == "UNCERTAIN":
                # Do NOT place an order automatically when uncertain.
                return {
                    "response": (
                        "I'm not sure what you mean. "
                        "Would you like to place your order now, or make changes?"
                    ),
                    "actions": [],
                }

            # intent_label == "OTHER" – fall through to AI response below.

    # ── Step 5: Fresh CONFIRM_ORDER intent (no prior pending state) ──────────
    # Handles cases where the customer types a confirmation phrase without a
    # preceding cart-modification step (e.g. direct "place order" button).
    if request.cart:
        # Reuse cached label from step 4 if available (avoids a second LLM call).
        intent_label = _cached_intent if _cached_intent else classify_order_intent(message)

        if intent_label == "CONFIRM_ORDER":
            pending_confirmation.pop(session_id, None)
            waiting_for_name[session_id] = True

            return {
                "response": (
                    "Great! Before I place your order, "
                    "may I know your name?"
                ),
                "actions": [],
            }

        if intent_label == "NEGATIVE":
            return {
                "response": "No problem. What would you like to add or change?",
                "actions": [],
            }

        if intent_label == "UNCERTAIN":
            return {
                "response": (
                    "I'm not sure what you mean. "
                    "Would you like to place your order, or is there something "
                    "else I can help with?"
                ),
                "actions": [],
            }

    # ── Step 6: AI conversational fallback ──────────────────────────────────
    ai_reply = get_ai_response(session_id, message, cart_str)

    # Honour ORDER CONFIRMED signal from the AI (legacy path kept for safety).
    if "ORDER CONFIRMED" in ai_reply and request.cart:
        pending_confirmation.pop(session_id, None)
        waiting_for_name[session_id] = True
        clean_reply = ai_reply.replace("ORDER CONFIRMED", "").strip()

        return {
            "response": clean_reply or (
                "Great! Before I place your order, "
                "may I know your name?"
            ),
            "actions": [],
        }

    return {
        "response": ai_reply,
        "actions": [],
    }


@app.post("/place_order")
async def place_order(order: OrderRequest):
    try:
        customer_name = order.customer.strip() if order.customer else ""
        if not customer_name:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "error": "Customer name is required before placing the order."}
            )

        if not order.items:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "error": "Your basket is empty. Add an item before placing an order."}
            )

        # Validate items & recalculate server-side totals
        validated_items = []
        total = 0

        for item in order.items:
            name = item.get("name")
            if not name or name not in MENU:
                continue

            try:
                qty = max(1, int(item.get("quantity", 1)))
            except (TypeError, ValueError):
                qty = 1

            price = MENU[name]
            subtotal = price * qty
            total += subtotal

            validated_items.append({
                "name": name,
                "quantity": qty,
                "price": price
            })

        if not validated_items:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "error": "No valid products found in basket."}
            )

        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        title_style.fontName = PDF_FONT_BOLD
        h2_style = styles["Heading2"]
        h2_style.fontName = PDF_FONT_NORMAL

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer)
        elements = []

        elements.append(
            Paragraph("<b>Savoury & Sweet Co.</b>", title_style)
        )
        elements.append(
            Paragraph(f"Customer : {customer_name}", h2_style)
        )

        data = [["Item", "Qty", "Price", "Subtotal"]]
        for item in validated_items:
            subtotal = item["price"] * item["quantity"]
            data.append([
                item["name"],
                str(item["quantity"]),
                f"₹{item['price']}",
                f"₹{subtotal}"
            ])

        data.append(["", "", "Total", f"₹{total}"])

        table = Table(data)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), PDF_FONT_NORMAL),
            ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
            ("FONTNAME", (-2, -1), (-1, -1), PDF_FONT_BOLD),
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 1), (-1, -2), colors.beige),
            ("BACKGROUND", (-2, -1), (-1, -1), colors.lightgrey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER")
        ]))

        elements.append(table)
        doc.build(elements)

        pdf_bytes = buffer.getvalue()
        buffer.close()

        safe_name = "".join(c for c in customer_name if c.isalnum()) or "Customer"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"Invoice_{safe_name}_{timestamp}.pdf"

        if supabase is None:
            raise HTTPException(
                status_code=500,
                detail="Supabase configuration missing: cannot store invoice or record order."
            )

        print("Uploading PDF...")
        upload = supabase.storage.from_("SweetInvoice").upload(
            path=file_name,
            file=pdf_bytes,
            file_options={
                "content-type": "application/pdf",
                "upsert": False
            }
        )
        print("Upload successful")

        invoice_url = supabase.storage.from_("SweetInvoice").get_public_url(file_name)

        response = supabase.table("orders").insert({
            "customer": customer_name,
            "items": validated_items,
            "total": total,
            "invoice_url": invoice_url
        }).execute()

        print("Inserted Successfully")

        return {
            "status": "success",
            "invoice_url": invoice_url
        }

    except HTTPException:
        raise
    except Exception as e:
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": str(e)}
        )


# ════════════════════════════════════════════════════════════════════
#  WHISPER TRANSCRIPTION (server-side, high-accuracy mode)
# ════════════════════════════════════════════════════════════════════

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Accepts an audio blob (webm/ogg/wav/mp4) and returns the transcription.
    Supports Groq Whisper (if GROQ_API_KEY is set) or OpenAI Whisper (if OPENAI_API_KEY is set).
    Returns structured JSON with error_category on failures for diagnostic clarity.
    """
    filename = file.filename or "audio.webm"
    content_type = file.content_type or "audio/webm"
    print(f"[WHISPER] Request received: filename={filename!r}, content_type={content_type!r}")

    try:
        audio_bytes = await file.read()
        byte_count = len(audio_bytes)
        print(f"[WHISPER] Diagnostic: filename={filename!r}, content_type={content_type!r}, byte_count={byte_count}")

        if byte_count == 0:
            print("[WHISPER] Failure: Received empty audio file (0 bytes)")
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Audio file is empty. Please speak into your microphone and try again.",
                    "error_category": "empty_audio",
                    "details": {"filename": filename, "content_type": content_type, "byte_count": 0}
                }
            )

        prompt_text = (
            "Savoury & Sweet Co. bakery items: Samosa, Vada Pav, Aloo Tikki, Kachori, Veg Puff, Paneer Puff, "
            "Masala Sandwich, Veg Sandwich, Cheese Sandwich, Cheesy Garlic Bread, Alfredo Spaghetti, "
            "Chocolate Cake, Vanilla Cake, Butterscotch Cake, Black Forest Cake, Red Velvet Cake, "
            "Butter Croissant, Chocolate Brownie, Cupcake, Chocolate Cupcake, Blueberry Muffin, "
            "Muffin, Choco Chip Cookies, Cookies, Donut, Chocolate Donut, Cold Coffee, Chocolate Shake, Mango Shake."
        )

        def clean_and_validate_transcript(raw_text: str):
            """
            Validates transcript text. Returns tuple: (valid_text_or_None, category_if_rejected)
            Categories: 'empty_transcription', 'rejected_transcription', or None (valid).
            """
            if not raw_text:
                return None, "empty_transcription"

            cleaned = raw_text.strip()
            lowered = cleaned.lower()

            if not cleaned or len(cleaned) < 2:
                return None, "empty_transcription"

            # Common Whisper subtitle hallucinations on brief/silent audio
            hallucination_triggers = [
                "sous-titrage", "sous-titres", "subtitles", "thank you for watching",
                "thanks for watching", "amara.org", "do not paraphrase", "mbc", "www.",
                "captioned", "transcription by", "translated by", "copyright"
            ]

            # Do not reject a transcript merely because it is short: valid orders such
            # as "Cake" or "Aloo Tikki" can be brief. Keep only the exact generic
            # filler phrases that commonly appear on silence, plus known artifacts.
            if lowered.rstrip(".!? ") in {"thank you", "thanks", "you"}:
                return None, "rejected_transcription"

            if any(h in lowered for h in hallucination_triggers):
                return None, "rejected_transcription"

            return cleaned, None

        # 1. Try Groq Whisper API if GROQ_API_KEY is configured
        if GROQ_API_KEY:
            try:
                print("[WHISPER] Attempting transcription via Groq API (whisper-large-v3)...")
                client_groq = Groq(api_key=GROQ_API_KEY)
                transcription = client_groq.audio.transcriptions.create(
                    file=(filename, audio_bytes),
                    model="whisper-large-v3",
                    response_format="json",
                    language="en",
                    temperature=0.0,
                    prompt=prompt_text
                )
                raw_text = transcription.text if hasattr(transcription, 'text') else str(transcription)
                valid_text, fail_cat = clean_and_validate_transcript(raw_text)

                if not valid_text:
                    # Avoid logging or returning raw speech transcripts; they may contain personal information.
                    print(f"[WHISPER] Groq transcript rejected: category={fail_cat!r}, transcript_length={len(raw_text or '')}")
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "Could not recognize clear speech from audio. Please speak clearly into your microphone.",
                            "error_category": fail_cat,
                            "details": {
                                "filename": filename,
                                "content_type": content_type,
                                "byte_count": byte_count,
                                "provider": "groq",
                                "transcript_length": len(raw_text or "")
                            }
                        }
                    )

                print(f"[WHISPER] Groq transcription success: {valid_text!r}")
                return JSONResponse(content={"transcript": valid_text, "provider": "groq"})

            except Exception as e:
                print(f"[WHISPER] Groq Whisper provider error: {e}")
                traceback.print_exc()
                if not OPENAI_API_KEY:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": f"Groq Whisper transcription failed: {str(e)}",
                            "error_category": "provider_error",
                            "details": {"provider": "groq", "filename": filename, "byte_count": byte_count}
                        }
                    )

        # 2. Try OpenAI Whisper API if OPENAI_API_KEY is configured
        if OPENAI_API_KEY:
            try:
                print("[WHISPER] Attempting transcription via OpenAI API (whisper-1)...")
                import openai
                client_oai = openai.OpenAI(api_key=OPENAI_API_KEY)
                transcription = client_oai.audio.transcriptions.create(
                    model="whisper-1",
                    file=(filename, audio_bytes),
                    language="en",
                    temperature=0.0,
                    prompt=prompt_text
                )
                raw_text = transcription.text
                valid_text, fail_cat = clean_and_validate_transcript(raw_text)

                if not valid_text:
                    # Avoid logging or returning raw speech transcripts; they may contain personal information.
                    print(f"[WHISPER] OpenAI transcript rejected: category={fail_cat!r}, transcript_length={len(raw_text or '')}")
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "Could not recognize clear speech from audio. Please speak clearly into your microphone.",
                            "error_category": fail_cat,
                            "details": {
                                "filename": filename,
                                "content_type": content_type,
                                "byte_count": byte_count,
                                "provider": "openai",
                                "transcript_length": len(raw_text or "")
                            }
                        }
                    )

                print(f"[WHISPER] OpenAI transcription success: {valid_text!r}")
                return JSONResponse(content={"transcript": valid_text, "provider": "openai"})

            except Exception as e:
                print(f"[WHISPER] OpenAI Whisper provider error: {e}")
                traceback.print_exc()
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": f"OpenAI Whisper transcription failed: {str(e)}",
                        "error_category": "provider_error",
                        "details": {"provider": "openai", "filename": filename, "byte_count": byte_count}
                    }
                )

        print("[WHISPER] Failure: Neither GROQ_API_KEY nor OPENAI_API_KEY is configured.")
        return JSONResponse(
            status_code=503,
            content={
                "error": "Whisper API key not configured (neither GROQ_API_KEY nor OPENAI_API_KEY set in environment).",
                "error_category": "config_error",
                "details": {"provider": "none"}
            }
        )

    except Exception as e:
        print(f"[WHISPER] Unexpected endpoint error: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Server transcription error: {str(e)}",
                "error_category": "server_error",
                "details": {"filename": filename}
            }
        )


# ════════════════════════════════════════════════════════════════════
#  ANALYTICS DASHBOARD ENDPOINTS
# ════════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={}
    )

@app.get("/api/analytics")
async def get_analytics():
    """Return analytics data in a robust, production‑friendly format.
    Includes summary metrics, aggregated trends, top product lists, and raw sanitized orders.
    Cleanly handles missing created_at fields via invoice URL parsing fallback.
    """
    try:
        # Fetch all orders from Supabase
        response = supabase.table("orders").select("*").execute()
        raw_orders = response.data or []

        sanitized_orders = []

        for order in raw_orders:
            # Skip invalid or test orders/customers
            cust_name = str(order.get("customer") or "").strip()
            if not cust_name or cust_name.lower() in ["test user", "test"]:
                continue

            # Extract date (prefer created_at, fallback to invoice_url regex, then current date)
            created_at = order.get("created_at")
            date_str = None
            if created_at:
                date_str = str(created_at)[:10]
            else:
                inv_url = str(order.get("invoice_url") or "")
                match = re.search(r'(\d{4})(\d{2})(\d{2})_\d{6}', inv_url)
                if match:
                    date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
                else:
                    date_str = datetime.now().strftime("%Y-%m-%d")

            # Clean order total
            order_total = float(order.get("total", 0) or 0)

            # Clean items array
            cleaned_items = []
            for item in order.get("items") or []:
                p_name = str(item.get("name") or "Unknown").strip()
                if p_name.lower() == "test":
                    continue
                p_qty = int(item.get("quantity", 1) or 1)
                p_price = float(item.get("price", 0) or 0)
                cleaned_items.append({
                    "name": p_name,
                    "quantity": p_qty,
                    "price": p_price,
                    "revenue": p_qty * p_price
                })

            sanitized_orders.append({
                "id": order.get("id"),
                "customer": cust_name,
                "date": date_str,
                "total": order_total,
                "items": cleaned_items
            })

        # Calculate backward-compatible aggregates
        total_revenue = sum(o["total"] for o in sanitized_orders)
        total_orders = len(sanitized_orders)
        total_units = sum(sum(i["quantity"] for i in o["items"]) for o in sanitized_orders)
        avg_order_val = total_revenue / total_orders if total_orders > 0 else 0.0

        revenue_by_date = {}
        items_by_date = {}
        product_sales = {}

        for o in sanitized_orders:
            d = o["date"]
            revenue_by_date[d] = revenue_by_date.get(d, 0.0) + o["total"]
            
            for item in o["items"]:
                pname = item["name"]
                qty = item["quantity"]
                rev = item["revenue"]
                items_by_date[d] = items_by_date.get(d, 0) + qty

                if pname not in product_sales:
                    product_sales[pname] = {"quantity": 0, "revenue": 0.0}
                product_sales[pname]["quantity"] += qty
                product_sales[pname]["revenue"] += rev

        sorted_dates = sorted(revenue_by_date.keys())
        trend_labels = sorted_dates
        trend_revenue = [round(revenue_by_date[d], 2) for d in sorted_dates]
        trend_items = [items_by_date.get(d, 0) for d in sorted_dates]

        sorted_products = sorted(product_sales.items(), key=lambda kv: kv[1]["quantity"], reverse=True)
        top_labels = [k for k, v in sorted_products]
        top_data = [v["quantity"] for k, v in sorted_products]

        return {
            "status": "success",
            "summary": {
                "total_revenue": round(total_revenue, 2),
                "total_orders": total_orders,
                "total_units": total_units,
                "avg_order_value": round(avg_order_val, 2)
            },
            "trends": {
                "labels": trend_labels,
                "revenue": trend_revenue,
                "items": trend_items
            },
            "top_products": {
                "labels": top_labels,
                "data": top_data
            },
            "orders": sanitized_orders
        }
    except Exception as e:
        print("Analytics error:")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

# ════════════════════════════════════════════════════════════════════
#  SERVER ENTRY POINT
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except OSError as e:
        print(f"\n❌  Port {port} is already in use.")
        print(f"   Try: set PORT=8001 && python main.py\n")
