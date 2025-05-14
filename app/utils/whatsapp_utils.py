from app.services.openai_service import generate_response
from openai import OpenAI
from app.services.openai_service import store_thread, client
import shelve
import time
import logging
from flask import current_app, jsonify
import json
import requests
import re
import os

def process_text_for_whatsapp(text):
    pattern = r"\【.*?\】"
    text = re.sub(pattern, "", text).strip()
    pattern = r"\*\*(.*?)\*\*"
    replacement = r"*\1*"
    whatsapp_style_text = re.sub(pattern, replacement, text)
    return whatsapp_style_text

def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)

def run_assistant(thread):
    assistant = client.beta.assistants.retrieve(os.getenv("OPENAI_ASSISTANT_ID"))
    logging.info(f"Starting run for assistant {assistant.id}")
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
    )
    logging.info(f"Run created: {run.id}")

    max_wait_time = 30
    elapsed_time = 0
    polling_interval = 0.5

    while run.status != "completed":
        if elapsed_time >= max_wait_time:
            logging.error(f"Timeout waiting for run {run.id}. Last status: {run.status}")
            return "Desculpe, não consegui processar sua solicitação a tempo."
        time.sleep(polling_interval)
        elapsed_time += polling_interval
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        logging.info(f"Run status: {run.status}")

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    new_message = messages.data[0].content[0].text.value
    logging.info(f"Generated message: {new_message}")
    return new_message

def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")

def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,  # Aqui usamos o recipient passado, que agora será o wa_id
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )

def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }
    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"
    logging.info(f"Sending message to WhatsApp: {data}")
    try:
        response = requests.post(url, data=data, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Request failed due to: {e}")
        logging.error(f"Response content: {e.response.text if e.response else 'No response'}")
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        log_http_response(response)
        return response

def process_whatsapp_message(body):
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message_body = message["text"]["body"]

    logging.info(f"Received message from wa_id: {wa_id}")
    response = generate_response(message_body, wa_id, name)
    response = process_text_for_whatsapp(response)

    # Adicione o '+' ao wa_id
    recipient = f"+{wa_id}"
    data = get_text_message_input(recipient, response)
    send_message(data)

def is_valid_whatsapp_message(body):
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )