import streamlit as st
import asyncio
import os
import json
import requests
from dotenv import load_dotenv
from agents import Agent, Runner, function_tool, OpenAIChatCompletionsModel
from openai import AsyncOpenAI

# -------------------- Load Environment --------------------
load_dotenv()

# Twilio / Webhook constants
VERCEL_WEBHOOK_URL = "https://giaic-q4.vercel.app/set-appointment"

TWILIO_FROM = "whatsapp:+14155238886"
PATIENT_NUMBER = "whatsapp:+923196560895"

# Gemini / OpenAI Model Setup
gemini_api_key = os.getenv("GEMINI_API_KEY")
external_client = AsyncOpenAI(
    api_key=gemini_api_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/"
)
model = OpenAIChatCompletionsModel(model="gemini-2.5-flash", openai_client=external_client)

# -------------------- Function Tools --------------------
@function_tool
def get_doctors() -> dict:
    """
    Returns a dictionary of available doctors along with their specialties and weekly availability schedule.

    This tool is used by the agent to:
    - Show the list of doctors
    - Match doctor names from user input
    - Provide exact availability (days and time ranges)
    - Validate appointment scheduling requests

    Doctors Available:
    ------------------
    1. Dr. Khan (Dermatologist)
       - Available: Monday to Friday
           • Morning: 10:00 AM – 2:00 PM
           • Evening: 7:00 PM – 10:00 PM

    2. Dr. Ahmed (Neurologist)
       - Available: Monday to Friday
           • Evening: 7:00 PM – 11:00 PM
       - Saturday:
           • Morning: 10:00 AM – 2:00 PM
           • Evening: 7:00 PM – 11:00 PM
    """
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
                "Monday to Friday": {
                    "Evening": "7:00 PM - 11:00 PM"
                },
                "Saturday": {
                    "Morning": "10:00 AM - 2:00 PM",
                    "Evening": "7:00 PM - 11:00 PM"
                }
            }
        }
    }


@function_tool
def send_doctor_request(patient_name: str, doctor_name: str, date: str, time: str) -> str:
    try:
        payload = {
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "date": date,
            "time": time
        }
        response = requests.post(
            VERCEL_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json=payload
        )
        if response.status_code == 200:
            return "✅ Doctor notified via webhook!"
        else:
            return f"❌ Doctor notification failed (status code {response.status_code})"
    except Exception as e:
        return f"❌ Webhook error: {str(e)}"

@function_tool
def confirm_patient(patient_name: str, doctor_name: str, date: str, time: str) -> str:
    try:
        message = f"✅ Hello {patient_name}, your appointment with {doctor_name} is confirmed on {date} at {time}."
        # NOTE: Twilio sending is now handled via webhook/confirmation logic
        save_to_json(patient_name, doctor_name, date, time)
        return "✅ Patient notified via WhatsApp (via webhook confirmation)."
    except Exception as e:
        return f"❌ Failed to notify patient: {e}"

def save_to_json(patient_name, doctor_name, date, time):
    record = {"patient": patient_name, "doctor": doctor_name, "date": date, "time": time}
    file = "appointments.json"
    try:
        data = json.load(open(file)) if os.path.exists(file) else []
        data.append(record)
        with open(file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"JSON save error: {e}")

# -------------------- Agents --------------------




agent = Agent(
    name="Doctor Assistant",
    instructions="""
You are a smart doctor appointment assistant.

Your responsibilities are:

🩺 1. **Doctor Availability**:  
If the user asks about available doctors or any doctor's schedule, use the `get_doctors` tool to fetch the list of doctors, their specialties, and their availability. Always verify that the doctor exists before proceeding.

📅 2. **Collect Appointment Details**:  
Ask the user to provide the following details:
- Patient's full name
- Doctor's name (must exist in get_doctors)
- Appointment date (should match the doctor's available days)
- Appointment time (should fall within the doctor's available time range)

✅ 3. **Confirm Appointment**:  
Once you have all details:
- Call `send_doctor_request` to notify the doctor (via webhook)
- Call `confirm_patient` to save and simulate notifying the patient

🧾 Format for internal tracking:
Return success or failure messages clearly, such as:
- “✅ Appointment booked successfully.”
- “❌ Doctor not available at this time.”
- “❌ Patient confirmation failed.”

Never guess availability — always use `get_doctors` tool when needed.
""",
    model=model,
    tools=[get_doctors, confirm_patient, send_doctor_request]
)




async def get_response(user_input: str) -> str:
    run_result = await Runner.run(agent, user_input)
    return run_result.final_output

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Doctor Appointment Assistant", page_icon="🩺")
st.title("🩺 Doctor Appointment Assistant")
st.markdown("This assistant helps you find a doctor and book an appointment via WhatsApp using Twilio.")

if "history" not in st.session_state:
    st.session_state.history = []

user_input = st.chat_input("Ask about doctor availability or book an appointment...")

for user_msg, assistant_msg in st.session_state.history:
    with st.chat_message("user"): st.markdown(user_msg)
    with st.chat_message("assistant"): st.markdown(assistant_msg)

if user_input:
    st.session_state.history.append((user_input, "thinking..."))
    st.rerun()

if st.session_state.history and st.session_state.history[-1][1] == "thinking...":
    last_user_message = st.session_state.history[-1][0]
    with st.spinner("Thinking..."):
        response = asyncio.run(get_response(last_user_message))
    st.session_state.history[-1] = (last_user_message, response)
    st.rerun()
