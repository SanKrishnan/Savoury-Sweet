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
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq
from typing import List, Dict, Any
from supabase import create_client
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import traceback

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

# ── Twilio ──────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_PHONE   = os.getenv("From_PHONE")
CUSTOMER_PHONE      = os.getenv("CUSTOMER_PHONE")
NGROK_URL           = os.getenv("NGROK_URL", "http://localhost:8000")

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
else:
    twilio_client = None

# ── OpenAI / Whisper (optional) ─────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower()
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
- Chocolate Cake: ₹500
- Vanilla Cupcakes (half dozen): ₹300
- Butter Croissant: ₹150
- Savoury Tart: ₹250
- Samosa: ₹20
- Vada Pav: ₹16
- Cheesy Garlic Bread: ₹150
- Butterscotch Cake: ₹350
- Alfredo Spaghetti: ₹250

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
    "Chocolate Cake": 500,
    "Vanilla Cupcakes (6)": 300,
    "Butter Croissant": 150,
    "Savoury Tart": 250,
    "Samosa": 20,
    "Vada Pav": 16,
    "Cheesy Garlic Bread": 150,
    "Butterscotch Cake": 350,
    "Alfredo Spaghetti": 250
}
NUMBER_WORDS = {
    "one":1,
    "two":2,
    "three":3,
    "four":4,
    "five":5,
    "six":6,
    "seven":7,
    "eight":8,
    "nine":9,
    "ten":10
}

def find_menu_item(text):
    text = text.lower()

    for item in MENU:
        if item.lower() in text:
            return item

    return None
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
    """Check if Ollama and the model are reachable."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        llama_ok = any("llama3.2" in m for m in models)
        return JSONResponse(content={
            "ollama": "running",
            "llama3.2": "available" if llama_ok else "not found – run: ollama pull llama3.2",
            "models": models
        })
    except Exception:
        return JSONResponse(
            content={"ollama": "not running – start with: ollama serve", "llama3.2": "unknown"},
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
    if not request.cart:
        cart_str = "Empty"
    else:
        cart_str = ", ".join(
            f"{i['quantity']}x {i['name']}"
            for i in request.cart
        )
    message = request.message.lower().strip()

    # ---------------- CLEAR CART ----------------
    if any(x in message for x in [
        "clear cart",
        "empty cart",
        "remove everything",
        "clear basket"
    ]):
        return {
            "response":
            "Your basket has been cleared. Would you like to start a new order?",
            "actions":[
                {
                    "action":"clear_cart"
                }
            ]
        }
# ---------------- KEEP ONLY ----------------
    if any(phrase in message for phrase in ["keep only", "only"]):
        item = find_menu_item(message)
        if item:
            # Reset cart to only this item with quantity 1
            new_cart = [{"name": item, "quantity": 1, "price": MENU[item]}]
            total = MENU[item]
            response_text = f"Added 1 {item} to your basket. Your current total is ₹{total}. Would you like to add anything else, remove or modify any item, or should I place your order? Reply yes to confirm."
            return {
                "response": response_text,
                "actions": [
                    {
                        "action": "keep_only",
                        "item": item,
                        "new_cart": new_cart,
                        "total": total
                    }
                ]
            }
    # ---------------- REMOVE ----------------
    if message.startswith("remove"):
        item = find_menu_item(message)
        if item:
            return {
                "response":
                f"{item} removed from your basket.",
                "actions":[
                    {
                        "action":"remove",
                        "item":item
                    }
                ]
            }
    ai_reply = get_ai_response(session_id, request.message, cart_str)
    lower = ai_reply.lower()
    if pending_confirmation.get(session_id):
        if message in ["yes","place order","confirm","ok","okay"]:
            pending_confirmation.pop(session_id)
            waiting_for_name[session_id] = True
            return {
                "response":
                "Great! Before I place your order, may I know your name?",
                "actions":[]
            }
    if waiting_for_name.get(session_id):
        waiting_for_name.pop(session_id)
        customer_names[session_id] = request.message.strip()
        return {
            "response":
            f"Thank you {customer_names[session_id]}.\n\nYour order has been confirmed.\nORDER CONFIRMED",
            "actions":[
                {
                    "action":"place_order",
                    "customer":customer_names[session_id]
                }
            ]
        }
    actions = []
    for item, price in MENU.items():

        if re.search(rf"\b{re.escape(item.lower())}\b", lower):
            number_words = {
                "one":1,
                "two":2,
                "three":3,
                "four":4,
                "five":5,
                "six":6,
                "seven":7,
                "eight":8,
                "nine":9,
                "ten":10
            }
            qty = 1
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
                    qty = NUMBER_WORDS[value]
                actions.append({
                    "action":"add",
                    "item":item,
                    "price":price,
                    "quantity":qty
                })
    if actions:
        pending_confirmation[session_id] = True
        return {
            "response": ai_reply,
            "actions": actions
        }
    return {
        "response": ai_reply,
        "actions":[]
    }
  
@app.post("/place_order")
async def place_order(order: OrderRequest):

    styles = getSampleStyleSheet()

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer)

    elements = []

    elements.append(
        Paragraph("<b>Savoury & Sweet Co.</b>", styles["Title"])
    )

    elements.append(
        Paragraph(f"Customer : {order.customer}", styles["Heading2"])
    )

    data = [["Item","Qty","Price","Subtotal"]]

    total = 0

    for item in order.items:

        subtotal = item["price"] * item["quantity"]

        total += subtotal

        data.append([
            item["name"],
            str(item["quantity"]),
            f"₹{item['price']}",
            f"₹{subtotal}"
        ])

    data.append(["","","Total",f"₹{total}"])

    table = Table(data)

    table.setStyle(TableStyle([
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
        c for c in order.customer if c.isalnum()
    )

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

        print(upload)
        print(type(upload))

        print("Upload successful")

        invoice_url = supabase.storage.from_("SweetInvoice").get_public_url(file_name)

        print(invoice_url)
        print(type(invoice_url))

        print(invoice_url)

        response = supabase.table("orders").insert({
            "customer": order.customer,
            "items": order.items,
            "total": total,
            "invoice_url": invoice_url
        }).execute()

        print(response)

        print("Inserted Successfully")

        return {
            "status":"success",
            "invoice_url":invoice_url
        }

    except Exception as e:

            print("="*60)
            traceback.print_exc()
            print("="*60)


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
#  TWILIO TELEPHONY ENDPOINTS
# ════════════════════════════════════════════════════════════════════

@app.post("/call_bakery")
async def initiate_call(request: Request):
    """Initiates an outbound call to the customer via Twilio."""
    if not twilio_client:
        return JSONResponse(
            content={"error": "Twilio credentials not configured. Please add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, From_PHONE, and CUSTOMER_PHONE to your .env file."},
            status_code=503,
        )
    if not CUSTOMER_PHONE or not TWILIO_FROM_PHONE:
        return JSONResponse(
            content={"error": "CUSTOMER_PHONE or From_PHONE not set in .env"},
            status_code=503,
        )
    try:
        call = twilio_client.calls.create(
            to=CUSTOMER_PHONE,
            from_=TWILIO_FROM_PHONE,
            url=f"{NGROK_URL}/voice",
        )
        return JSONResponse(content={"status": "calling", "sid": call.sid})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.api_route("/voice", methods=["GET", "POST"])
async def voice_webhook(request: Request):
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        action="/process_speech",
        timeout=5,
        speechTimeout="auto",
        language="en-IN",
    )
    gather.say("Welcome to Savoury and Sweet Company! How can I help you today?", voice="Polly.Aditi")
    response.redirect("/voice")
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.api_route("/process_speech", methods=["GET", "POST"])
async def process_speech(request: Request):
    form_data = await request.form()
    user_speech = form_data.get("SpeechResult", "")
    call_sid = form_data.get("CallSid", "unknown_call")

    response = VoiceResponse()
    if user_speech:
        ai_reply = get_ai_response(call_sid, user_speech)
        gather = response.gather(
            input="speech",
            action="/process_speech",
            timeout=5,
            speechTimeout="auto",
            language="en-IN",
        )
        gather.say(ai_reply, voice="Polly.Aditi")
        response.say("Thank you for calling. Goodbye!", voice="Polly.Aditi")
        response.hangup()
    else:
        response.say("I didn't quite catch that. Could you say that again?", voice="Polly.Aditi")
        response.redirect("/voice")

    return HTMLResponse(content=str(response), media_type="application/xml")


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
