from openai import OpenAI, NotFoundError
import shelve
from dotenv import load_dotenv
import os
import time
import logging

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)

def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)

def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id

def run_assistant(thread):
    assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)
    logging.info(f"Starting run for assistant {assistant.id}")
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
    )
    logging.info(f"Run created: {run.id}")

    max_wait_time = 30
    elapsed_time = 0
    polling_interval = 29

    while run.status != "completed":
        if elapsed_time >= max_wait_time:
            logging.error(f"Timeout waiting for run {run.id}. Last status: {run.status}")
            return "Desculpe, não consegui processar sua solicitação a tempo. Tente novamente!"
        time.sleep(polling_interval)
        elapsed_time += polling_interval
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        logging.info(f"Run status: {run.status}")

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    new_message = messages.data[0].content[0].text.value
    logging.info(f"Generated message: {new_message}")
    return new_message

def generate_response(message_body, wa_id, name):
    thread_id = check_if_thread_exists(wa_id)
    thread = None

    if thread_id is not None:
        try:
            logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
            thread = client.beta.threads.retrieve(thread_id)
        except NotFoundError:  # Captura o erro 404
            logging.warning(f"Thread {thread_id} not found on OpenAI. Creating a new one for {wa_id}.")
            thread_id = None

    if thread_id is None or thread is None:
        logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.create()
        store_thread(wa_id, thread.id)

    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=message_body,
    )
    new_message = run_assistant(thread)
    logging.info(f"To {name}: {new_message}")
    return new_message