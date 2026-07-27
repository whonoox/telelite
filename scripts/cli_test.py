#!/usr/bin/env python3
"""Manual, interactive test client for the TeleLite Phase 1 API.

Run the server first (`python run.py`), then run this script against your
own Telegram account/phone to walk through the full login -> chats ->
messages -> send -> logout flow.
"""
import sys

import requests

BASE_URL = "http://127.0.0.1:5000"


def request_login():
    phone_number = input("Phone number (with country code, e.g. +1555...): ").strip()
    resp = requests.post(f"{BASE_URL}/login/request", json={"phone_number": phone_number})
    data = resp.json()
    if resp.status_code != 200:
        print(f"Error: {data}")
        sys.exit(1)
    return phone_number, data["pending_id"]


def verify_login(pending_id):
    code = input("Login code sent to your Telegram: ").strip()
    payload = {"pending_id": pending_id, "code": code}
    resp = requests.post(f"{BASE_URL}/login/verify", json=payload)
    data = resp.json()
    if resp.status_code == 400 and data.get("error") == "needs_password":
        password = input("2FA password: ").strip()
        payload["password"] = password
        resp = requests.post(f"{BASE_URL}/login/verify", json=payload)
        data = resp.json()
    if resp.status_code != 200:
        print(f"Error: {data}")
        sys.exit(1)
    return data["token"]


def list_chats(headers):
    resp = requests.get(f"{BASE_URL}/chats", headers=headers)
    data = resp.json()
    if resp.status_code != 200:
        print(f"Error: {data}")
        return []
    chats = data["chats"]
    print("\nRecent chats:")
    for i, chat in enumerate(chats):
        print(f"  [{i}] {chat['name']} (id={chat['chat_id']}, unread={chat['unread_count']})")
        if chat.get("last_message"):
            print(f"       last: {chat['last_message'][:60]}")
    return chats


def view_messages(headers, chat_id):
    resp = requests.get(f"{BASE_URL}/chats/{chat_id}/messages", headers=headers)
    data = resp.json()
    if resp.status_code != 200:
        print(f"Error: {data}")
        return
    print(f"\nMessages in chat {chat_id} (oldest -> newest):")
    for m in data["messages"]:
        who = "me" if m["out"] else "them"
        print(f"  [{m['id']}] ({who}) {m['text']}")


def send_message(headers, chat_id):
    text = input("Message text to send: ").strip()
    if not text:
        print("Empty message, skipping send.")
        return
    resp = requests.post(f"{BASE_URL}/chats/{chat_id}/messages", headers=headers, json={"text": text})
    data = resp.json()
    if resp.status_code != 200:
        print(f"Error: {data}")
    else:
        print(f"Sent: {data['message']}")


def logout(headers):
    resp = requests.post(f"{BASE_URL}/logout", headers=headers)
    print(f"Logout: {resp.json()}")


def main():
    print("=== TeleLite Phase 1 CLI test ===")
    _, pending_id = request_login()
    token = verify_login(pending_id)
    print("Logged in.")
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        chats = list_chats(headers)
        choice = input(
            "\nEnter chat index to open, or 'q' to logout and quit: "
        ).strip()
        if choice.lower() == "q":
            break
        try:
            chat = chats[int(choice)]
        except (ValueError, IndexError):
            print("Invalid choice.")
            continue

        view_messages(headers, chat["chat_id"])
        action = input("\n's' to send a message, anything else to go back to chat list: ").strip()
        if action.lower() == "s":
            send_message(headers, chat["chat_id"])
            view_messages(headers, chat["chat_id"])
            input("Press enter to return to chat list...")

    logout(headers)
    print("Done.")


if __name__ == "__main__":
    main()
