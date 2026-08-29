# 🧁 Savoury & Sweet Co. — AI Bakery Assistant

### *A Hybrid Local-First & Production-Grade Conversational AI Ordering Platform*

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-brightgreen?style=for-the-badge&logo=vercel&logoColor=white)](https://savoury-sweet.vercel.app/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![AI Engine](https://img.shields.io/badge/AI%20Engine-Llama%203.2%20%2F%203.3-blueviolet?style=for-the-badge&logo=meta&logoColor=white)](#-dual-environment-engine)
[![Analytics](https://img.shields.io/badge/Analytics-Chart.js%20%26%20Power%20BI-F2C811?style=for-the-badge&logo=powerbi&logoColor=black)](#-executive-analytics-dashboard-chartjs--power-bi)

**🌐 Live Demo:** https://savoury-sweet.vercel.app/

---

# 🌟 Overview

**Savoury & Sweet Co.** is an AI-powered conversational bakery ordering platform that enables customers to browse a bakery menu, place orders using natural language or voice, and automatically generate invoices stored securely in the cloud.

The application combines modern web technologies with Large Language Models to provide a natural ordering experience across desktop and mobile devices.

---

# ⚡ Dual-Environment AI Engine

To balance offline development and cloud deployment, the application supports two AI providers.

```mermaid
graph TD
    A[Customer] --> B{AI Provider}
    B -->|Local| C[Ollama - Llama 3.2]
    B -->|Production| D[Groq - Llama 3.3 70B]
    C --> E[FastAPI Backend]
    D --> E
    E --> F[Supabase Database]
    E --> G[Supabase Storage]
```

### Local Development

* Ollama
* Llama 3.2
* Offline development
* Zero API cost

### Production

* Groq API
* Llama 3.3 70B
* Fast inference
* Cloud hosted

---

# 🚀 Features

### 🤖 AI Ordering Assistant

* Conversational food ordering
* Natural language understanding
* Voice-enabled ordering
* Multi-turn conversations
* Dynamic shopping basket

### 🍰 Intelligent Product Assistant

The AI can answer questions such as:

* How does Chocolate Cake taste?
* Is the Alfredo Spaghetti spicy?
* What does the Butterscotch Cake look like?
* Which item would you recommend?

It provides natural descriptions of menu items, flavours, textures, ingredients, and recommendations to help customers decide before ordering.

---

### 🛒 Smart Cart Management

Supports conversational commands like:

* Add 2 Chocolate Cakes
* Remove Samosa
* Keep only one Butter Croissant
* Clear Basket
* Modify quantities

The basket updates dynamically in real time.

---

### 🎤 Voice Interaction

Supports

* Browser Speech Recognition
* Browser Speech Synthesis
* OpenAI Whisper (optional)
* Voice replies from the AI assistant

---

### 📊 Executive Analytics Dashboard (Chart.js & Power BI)

The platform includes a real-time business intelligence and analytics suite to monitor bakery performance and ordering trends:

* **In-App Analytics Dashboard (`/dashboard`)**: Built with **Chart.js** and Tailwind CSS, providing real-time KPI tracking for **Total Revenue**, **Total Orders**, **Units Sold**, and **Average Order Value (AOV)**.
* **Interactive Visualizations**: Dynamic charts for daily revenue trajectories, product category sales mix, best-selling bakery items, and unit volume metrics.
* **Flexible Date Horizons & Filtering**: Instant time-range slicing (*Today*, *This Week*, *This Month*, *This Quarter*, *This Year*, *All-Time*) and per-product performance breakdowns.
* **Power BI Local Integration**: Connect **Microsoft Power BI** locally to the Supabase PostgreSQL database or local backend to build advanced business intelligence reports, custom DAX measures, predictive sales forecasting, and executive reporting locally on your desktop.

---

### 📄 Invoice Generation

After confirmation, the application

* Generates a PDF invoice using ReportLab (with full Unicode ₹ symbol support)
* Uploads the invoice to **Supabase Storage**
* Stores order details in the **Supabase Orders Table**
* Returns a public invoice URL

---

### ☁️ Cloud Storage

Supabase is used for

* Orders Table
* Invoice Storage Bucket
* Public Invoice URLs

---

### 📱 Responsive Interface

The interface is fully responsive and optimized for

* Desktop
* Tablets
* Mobile Phones

Customers can browse the menu, interact with the AI assistant, and place orders seamlessly across different screen sizes.

---

# 🛠 Tech Stack

### Frontend

* HTML5
* CSS3
* JavaScript
* Tailwind CSS
* Chart.js (Real-time Web Analytics Dashboard)

### Backend

* FastAPI
* Python

### AI

* Groq API
* Ollama
* Llama 3.2
* Llama 3.3 70B

### Cloud & Database

* Supabase Database (PostgreSQL)
* Supabase Storage (Invoices)

### Analytics & Business Intelligence

* **Chart.js** (In-app real-time analytics)
* **Power BI** (Local desktop BI analytics, custom DAX metrics & executive reporting)

### Utilities

* ReportLab (PDF Invoice Generation with Unicode TTF support)
* Jinja2
* Python Speech APIs

### Deployment

* Vercel (Frontend)
* Render / FastAPI Backend
* Supabase

---

# 📦 Installation

## Clone Repository

```bash
git clone https://github.com/SanKrishnan/Savoury-Sweet.git
cd Savoury-Sweet
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Create a `.env`

```env
SUPABASE_URL=YOUR_URL
SUPABASE_KEY=YOUR_KEY

AI_PROVIDER=groq

GROQ_API_KEY=YOUR_KEY

OLLAMA_MODEL=llama3.2

OPENAI_API_KEY=YOUR_KEY
```

---

## Run Locally

```bash
python main.py
```

* **Storefront & AI Assistant:** `http://localhost:8000`
* **Executive Analytics Dashboard:** `http://localhost:8000/dashboard`

### 📊 Power BI Local Integration

To run Power BI reports locally with live bakery order data:

1. Open **Microsoft Power BI Desktop**.
2. Select **Get Data** &rarr; **PostgreSQL database** (or **Web / REST API** pointing to `http://localhost:8000/api/analytics`).
3. Connect using your Supabase database credentials or local analytics endpoint.
4. Model your datasets to analyze sales trends, top product margins, and customer order behaviors in Power BI with custom DAX measures and visualizations.

---

# 🧪 Try It

Ask the assistant things like

* Add two Chocolate Cakes
* Remove the Samosa
* Keep only one Vada Pav
* How does the Butterscotch Cake taste?
* What does the Alfredo Spaghetti look like?
* Which dessert do you recommend?
* Place my order

---

# ☁️ Deployment

Frontend

* Vercel

Backend

* FastAPI on Render

Database & Storage

* Supabase

---

# 📷 Screenshots

## 🏠 Homepage

![Homepage](Screenshots/Homepage.png)

---

## 🤖 AI Conversation

![AI Chat](Screenshots/Chat.png)

---

## 📱 Mobile Homepage

![Mobile Homepage](Screenshots/Mobile_Homepage.jpeg)

---

## 💬 Mobile AI Chat

![Mobile Chat](Screenshots/Mobile_Chatbot.jpeg)

---

## 📋 Orders Stored in Supabase Table

![Supabase Table](Screenshots/Table.png)

---

## 🗂️ Invoice Stored in Supabase Storage

![Supabase Storage](Screenshots/Bucket_storage.png)

---

## 🧾 Orders Database

![Orders](Screenshots/List_orders.png)

---

# 🤝 Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push your branch
5. Open a Pull Request

---

# 📄 License

Licensed under the MIT License.
