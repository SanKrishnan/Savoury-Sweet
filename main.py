import os
import io
import re
import requests
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File
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

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)
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
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
)

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


class ChatRequest(BaseModel):
    message: str
    cart: List[Dict[str, Any]] = []

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
]

def find_menu_item(text):
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
    text = user_text.lower().strip()
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

    # 3. Check MULTI-ITEM OR SINGLE ITEM ADD/SET/REDUCE
    is_global_set = bool(re.match(r"^(make|set)\b", text))
    segments = re.split(r"[,+&]|\b(?:and|plus)\b", text)

    for seg in segments:
        seg_str = seg.strip()
        if not seg_str:
            continue

        item = find_menu_item(seg_str)
        if not item:
            continue

        num = extract_number(seg_str)
        qty = num if num is not None else 1

        if "remove" in seg_str or "delete" in seg_str or "drop" in seg_str:
            if "one" in seg_str or "1" in seg_str:
                actions.append({"action": "reduce_quantity", "item": item, "quantity": qty})
            else:
                actions.append({"action": "remove_item", "item": item})
        elif "reduce" in seg_str or "decrease" in seg_str or "minus" in seg_str:
            actions.append({"action": "reduce_quantity", "item": item, "quantity": qty})
        elif any(k in seg_str for k in ["make", "set", "only"]) or is_global_set:
            actions.append({"action": "set_quantity", "item": item, "price": MENU[item], "quantity": qty})
        elif "another" in seg_str or "more" in seg_str or "add" in seg_str or "plus" in seg_str:
            actions.append({"action": "add_quantity", "item": item, "price": MENU[item], "quantity": qty})
        else:
            actions.append({"action": "add_quantity", "item": item, "price": MENU[item], "quantity": qty})

    if actions:
        return actions

    fallback_item = cart_list[-1]["name"] if cart_list else None
    if fallback_item:
        num = extract_number(text)
        qty = num if num is not None else 1
        if any(k in text for k in ["make", "set", "only"]):
            return [{"action": "set_quantity", "item": fallback_item, "price": MENU[fallback_item], "quantity": qty}]
        elif any(k in text for k in ["reduce", "decrease", "remove one", "minus"]):
            return [{"action": "reduce_quantity", "item": fallback_item, "quantity": qty}]
        elif any(k in text for k in ["add", "more", "another"]):
            return [{"action": "add_quantity", "item": fallback_item, "price": MENU[fallback_item], "quantity": qty}]

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
    session_id = "web_user_123"
    message = request.message.strip()
    message_lower = message.lower()

    if not request.cart:
        cart_str = "Empty"
    else:
        cart_str = ", ".join(
            f"{i['quantity']}x {i['name']}"
            for i in request.cart
        )

    # 1. ALWAYS run the deterministic parser first.
    #    Cart-modification intents (replace, add, set, remove, clear) must never
    #    be blocked by the pending_confirmation gate — a user can change their
    #    mind at any point during the order flow.
    intent_actions = parse_cart_intent(message, request.cart)

    if intent_actions:
        # Any real cart action clears the confirmation gate
        pending_confirmation.pop(session_id, None)

        # Set pending confirmation if any action modified the cart (and not clear_cart)
        if not (len(intent_actions) == 1 and intent_actions[0].get("action") == "clear_cart"):
            pending_confirmation[session_id] = True

        resp_text = build_cart_response(intent_actions)
        return {
            "response": resp_text,
            "actions": intent_actions
        }

    # 2. No cart-modify intent — now check the confirmation gate.
    if waiting_for_name.get(session_id):
        waiting_for_name.pop(session_id)
        cust_name = message.strip() or "Guest Customer"
        customer_names[session_id] = cust_name
        return {
            "response": f"Thank you {cust_name}.\n\nYour order has been confirmed.\nORDER CONFIRMED",
            "actions": [
                {
                    "action": "place_order",
                    "customer": cust_name
                }
            ]
        }

    if pending_confirmation.get(session_id):
        if message_lower in ["yes", "place order", "confirm", "ok", "okay", "proceed"]:
            pending_confirmation.pop(session_id)
            waiting_for_name[session_id] = True
            return {
                "response": "Great! Before I place your order, may I know your name?",
                "actions": []
            }

    # 3. Fallback to AI LLM response
    ai_reply = get_ai_response(session_id, request.message, cart_str)
    lower = ai_reply.lower()

    actions = []
    for item, price in MENU.items():
        if re.search(rf"\b{re.escape(item.lower())}\b", lower):
            match = re.search(
                rf"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+{re.escape(item.lower())}",
                lower
            )
            qty = 1
            if match:
                value = match.group(1)
                if value.isdigit():
                    qty = int(value)
                else:
                    qty = NUMBER_WORDS.get(value, 1)
            actions.append({
                "action": "add_quantity",
                "item": item,
                "price": price,
                "quantity": qty
            })

    if actions:
        pending_confirmation[session_id] = True
        return {
            "response": ai_reply,
            "actions": actions
        }

    return {
        "response": ai_reply,
        "actions": []
    }

  
@app.post("/place_order")
async def place_order(order: OrderRequest):
    if not order.items:
        return JSONResponse(status_code=400, content={"status": "error", "error": "Your basket is empty. Add an item before placing an order."})

    # Validate items & recalculate server-side totals
    validated_items = []
    total = 0
    for item in order.items:
        name = item.get("name")
        if not name or name not in MENU:
            continue
        qty = max(1, int(item.get("quantity", 1)))
        price = MENU[name]
        subtotal = price * qty
        total += subtotal
        validated_items.append({
            "name": name,
            "quantity": qty,
            "price": price
        })

    if not validated_items:
        return JSONResponse(status_code=400, content={"status": "error", "error": "No valid products found in basket."})

    customer_name = order.customer.strip() if order.customer else "Guest Customer"

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
    data = [["Item","Qty","Price","Subtotal"]]
    for item in validated_items:
        subtotal = item["price"] * item["quantity"]
        data.append([
            item["name"],
            str(item["quantity"]),
            f"₹{item['price']}",
            f"₹{subtotal}"
        ])
    data.append(["","","Total",f"₹{total}"])
    table = Table(data)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT_NORMAL),
        ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
        ("FONTNAME", (-2, -1), (-1, -1), PDF_FONT_BOLD),
        ("BACKGROUND",(0,0),(-1,0),colors.grey),
        ("TEXTCOLOR",(0,0),(-1,0),colors.whitesmoke),
        ("GRID",(0,0),(-1,-1),1,colors.black),
        ("BACKGROUND",(0,1),(-1,-2),colors.beige),
        ("BACKGROUND",(-2,-1),(-1,-1),colors.lightgrey),
        ("ALIGN",(0,0),(-1,-1),"CENTER")
    ]))
    elements.append(table)
    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    safe_name = "".join(
        c for c in customer_name if c.isalnum()
    ) or "Guest"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"Invoice_{safe_name}_{timestamp}.pdf"
    try:
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

    except Exception as e:
        print("="*60)
        traceback.print_exc()
        print("="*60)
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

# ════════════════════════════════════════════════════════════════════
#  WHISPER TRANSCRIPTION (server-side, high-accuracy mode)
# ════════════════════════════════════════════════════════════════════

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Accepts an audio blob (webm/ogg/wav) and returns the transcription.
    Uses OpenAI Whisper if OPENAI_API_KEY is set, otherwise returns an error
    so the client can fall back to the browser SpeechRecognition.
    """
    if not OPENAI_API_KEY:
        return JSONResponse(
            content={"error": "OpenAI API key not configured. Using browser speech recognition."},
            status_code=503,
        )

    try:
        import openai
        client_oai = openai.OpenAI(api_key=OPENAI_API_KEY)
        audio_bytes = await file.read()
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = file.filename or "audio.webm"

        transcript = client_oai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="hi",          # Hint: Indian English / Hindi mix
            prompt="This is a bakery ordering conversation in Indian English.",
        )
        return JSONResponse(content={"transcript": transcript.text})
    except Exception as e:
        print(f"Whisper error: {e}")
        # Return an 'error' key (not a 500) so the browser JS silently falls back to Web Speech API
        return JSONResponse(content={"error": "Whisper unavailable", "detail": str(e)}, status_code=200)

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
