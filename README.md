# AI Bakery Assistant: Hybrid Voice & Web Platform

This project is a full-stack Conversational AI platform designed for a local fictional bakery ("Sweet Bites Bakery"). It utilizes a locally hosted Large Language Model (Llama 3.2 via Ollama) to answer customer inquiries and take cake orders.

This project was built to demonstrate advanced Gen AI engineering skills, specifically the ability to build robust, multi-channel AI systems that don't rely entirely on paid third-party APIs.

## Architecture Highlights
- **Backend**: FastAPI
- **AI Engine**: Llama 3.2 (Locally hosted via Ollama)
- **Primary Interface (Telephony)**: Twilio Webhooks for real-time phone conversations.
- **Fallback Interface (Web)**: HTML/CSS/JS frontend utilizing native browser `SpeechRecognition` and `SpeechSynthesis` APIs for cost-free, highly available interactions.

## Why this Architecture?
Many Gen AI projects rely heavily on paid APIs (like OpenAI or Twilio). If a trial expires, the project breaks, and recruiters cannot test it. This hybrid approach ensures 100% uptime:
1. It shows you know how to work with complex telecom APIs (Twilio).
2. It shows engineering maturity by providing a fully functional Web UI fallback that costs absolutely nothing to run.

## Setup Instructions

### Prerequisites
1. **Python 3.8+**
2. **Ollama**: Download and install Ollama from [ollama.com](https://ollama.com/).
3. Pull the Llama 3.2 model:
   ```bash
   ollama run llama3.2
   ```

### Installation
1. Clone the repository and navigate to the project directory.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Application

1. **Start the FastAPI Server:**
   ```bash
   python main.py
   ```
   *The server will start on `http://localhost:8000`.*

2. **Accessing the Web UI (The Recruiter Fallback):**
   Open your browser and navigate to `http://localhost:8000`. You can type your messages or click the microphone button to speak directly to the AI Assistant.

3. **Setting up Twilio (The Telephony Interface):**
   - Since the server is running locally, use [ngrok](https://ngrok.com/) to expose port 8000 to the internet:
     ```bash
     ngrok http 8000
     ```
   - Copy the forwarding URL provided by ngrok (e.g., `https://abc-123.ngrok.io`).
   - Go to your Twilio Console -> Phone Numbers -> Manage.
   - Under the **Voice & Fax** section, set the "A CALL COMES IN" webhook to: `https://abc-123.ngrok.io/voice` (HTTP POST).
   - Call your Twilio phone number and talk to the Sweet Bites Bakery AI!

## File Structure
- `main.py`: The core FastAPI application handling all routing and LLM logic.
- `templates/index.html`: The frontend UI.
- `requirements.txt`: Python dependencies.
- `.env`: (Optional) Environment variables for future expansions.
