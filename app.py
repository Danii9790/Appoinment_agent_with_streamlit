
import streamlit as st
import asyncio
import os
import json
import requests
from dotenv import load_dotenv
from agents import Agent, Runner, function_tool, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from typing import Dict

# -------------------- Load Environment --------------------
load_dotenv()

# Twilio / Webhook constants
VERCEL_WEBHOOK_URL = "https://giaic-q4.vercel.app/set-appointment"  # Update this if needed
TWILIO_FROM = "whatsapp:+14155238886"
PATIENT_NUMBER = "whatsapp:+923196560895"  # Replace with dynamic value in production

# Gemini Model Setup
external_client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/"
)
model = OpenAIChatCompletionsModel(model="gemini-2.5-flash", openai_client=external_client)

# -------------------- Function Tools --------------------
SANITY_PROJECT_ID = os.getenv("SANITY_PROJECT_ID")
SANITY_DATASET = os.getenv("SANITY_DATASET")
SANITY_TOKEN = os.getenv("SANITY_TOKEN")
SANITY_API_URL = f"https://{SANITY_PROJECT_ID}.api.sanity.io/v2023-07-19/data/mutate/{SANITY_DATASET}"

# ✅ Save to Sanity
@function_tool
def save_appointment(patientName: str, email: str, doctorName: str, date: str, time: str) -> str:
    query = {
        "query": '*[_type == "appointment" && doctorName == $doctorName && date == $date && time == $time][0]',
        "params": {"doctorName": doctorName, "date": date, "time": time}
    }
    check = requests.post(
        f"https://{SANITY_PROJECT_ID}.api.sanity.io/v2023-07-19/data/query/{SANITY_DATASET}",
        headers={"Authorization": f"Bearer {SANITY_TOKEN}"},
        json=query
    )
    if check.status_code == 200 and check.json().get("result"):
        return "⛔ Sorry, this time slot is already booked!"

    doc = {
        "mutations": [
            {"create": {
                "_type": "appointment",
                "patientName": patientName,
                "email": email,
                "doctorName": doctorName,
                "date": date,
                "time": time,
                "status": "pending"
            }}
        ]
    }
    response = requests.post(SANITY_API_URL, headers={"Authorization": f"Bearer {SANITY_TOKEN}"}, json=doc)
    return "✅ Appointment saved to Sanity." if response.status_code == 200 else "❌ Sanity save failed."

# 🧠 Doctor Data
@function_tool
def get_doctors() -> Dict:
    return {
        "Dr. Khan": {
            "specialty": "Dermatologist",
            "availability": {
                "Monday to Friday": {
                    "Morning": "10:00 AM - 2:00 PM",
                    "Evening": "7:00 PM - 10:00 PM"
                }
            }
        },
        "Dr. Ahmed": {
            "specialty": "Neurologist",
            "availability": {
                "Monday to Friday": {"Evening": "7:00 PM - 11:00 PM"},
                "Saturday": {
                    "Morning": "10:00 AM - 2:00 PM",
                    "Evening": "7:00 PM - 11:00 PM"
                }
            }
        }
    }

# 🕊️ Simulate WhatsApp to Doctor
@function_tool
def send_doctor_request(patient_name: str, doctor_name: str, date: str, time: str) -> str:
    payload = {"patient_name": patient_name, "doctor_name": doctor_name, "date": date, "time": time}
    try:
        response = requests.post(VERCEL_WEBHOOK_URL, headers={"Content-Type": "application/json"}, json=payload)
        return "✅ Doctor notified via webhook!" if response.status_code == 200 else f"❌ Webhook failed ({response.status_code})"
    except Exception as e:
        return f"❌ Webhook error: {str(e)}"

# ✅ Patient Confirmation (Local)
@function_tool
def confirm_patient(patient_name: str, doctor_name: str, date: str, time: str) -> str:
    try:
        file = "appointments.json"
        data = json.load(open(file)) if os.path.exists(file) else []
        for a in data:
            if a["doctor"] == doctor_name and a["date"] == date and a["time"] == time:
                return "❌ Doctor already booked at that time."
        data.append({"patient": patient_name, "doctor": doctor_name, "date": date, "time": time})
        with open(file, "w") as f: json.dump(data, f, indent=2)
        return f"✅ Appointment confirmed for {patient_name} with {doctor_name} on {date} at {time}."
    except Exception as e:
        return f"❌ Failed to confirm appointment: {e}"

# 🧠 Future Tool: Dynamic FunctionTool (for paid Twilio) ➤ If Twilio upgraded, use dynamic patient/doctor numbers
# def send_whatsapp_dynamic(from_number, to_number, msg):
#     Use Twilio API here...

# -------------------- Agent --------------------
agent = Agent(
    name="Doctor Assistant",
    instructions="""
You are a reliable and intelligent Doctor Appointment Assistant.

Your job is to **help patients book appointments with available doctors**. Follow the exact thinking steps and tool order to ensure safe, error-free bookings.

========================
💡 Your Capabilities
========================

1. 🩺 **Doctor Info**
   - Use `get_doctors` to fetch doctors, their specialties, and schedules.
   - Only book appointments with valid doctors.

2. 📅 **Booking an Appointment**
   - Ask the user for these details **step by step**:
     - Patient’s full name
     - Doctor’s name (must exist in doctor list)
     - Appointment date (must match availability)
     - Appointment time (must be in time range)

   - Validate doctor name and schedule using `get_doctors` before confirming.

3. ✅ **After collecting all data:**
   - Step 1: Call `send_doctor_request` to notify the doctor (Webhook).
   - Step 2: Call `save_appointment` to save to Sanity (backend DB).
   - Step 3: Call `confirm_patient` to log it locally and simulate patient notification.

4. 📲 **WhatsApp Logic**
   - Do NOT send WhatsApp directly. Assume it is handled outside this agent for now.
   - Only simulate confirmation.

========================
🧠 How to Think Internally
========================

- If doctor name is unknown → use `get_doctors`.
- If time or day mismatch → explain and ask again.
- Always check and confirm doctor availability before saving.
- Use polite tone. Guide the user if they are missing info.
- Don’t skip any tool in the appointment workflow.

========================
🔁 Return clear messages
========================

- ✅ “Appointment booked successfully.”
- ⛔ “Doctor not available on that day.”
- ❌ “Failed to save appointment to backend.”

NEVER guess or hallucinate schedule info. Always call tools.
"""
,
    model=model,
    tools=[get_doctors, send_doctor_request, save_appointment, confirm_patient]
)

async def get_response(user_input: str) -> str:
    async for chunk in Runner.run_streamed(agent, user_input):
        yield chunk.delta

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Doctor Appointment Assistant", page_icon="🩺")
st.title("🩺 Doctor Appointment Assistant")

if "history" not in st.session_state:
    st.session_state.history = []

user_input = st.chat_input("Ask about doctor availability or book an appointment...")

for user_msg, assistant_msg in st.session_state.history:
    with st.chat_message("user"): st.markdown(user_msg)
    with st.chat_message("assistant"): st.markdown(assistant_msg)

if user_input:
    with st.chat_message("user"): st.markdown(user_input)
    st.session_state.history.append((user_input, "thinking..."))
    with st.chat_message("assistant"):
        full_response = ""
        with st.spinner("Thinking..."):
            for token in asyncio.run(get_response(user_input)):
                full_response += token
                st.write(full_response)
        st.session_state.history[-1] = (user_input, full_response)
