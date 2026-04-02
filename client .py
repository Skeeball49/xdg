"""
NSS Client — Full Implementation
Protocol: flat text. Multi-word fields are automatically quoted before sending.
The user just types normally — the client wraps in quotes for them.
"""

import socket
import threading
import time
import sys
import os
import shlex
from datetime import datetime

SERVER_TCP_PORT = 10000
SERVER_UDP_PORT = 20000
CLIENT_TCP_PORT = 12000
CLIENT_UDP_PORT = 22000

DISCOVERY_MSG     = "NSS_DISCOVER"
DISCOVERY_TIMEOUT = 3
MAX_RETRIES       = 3
RETRY_DELAY       = 5

VALID_SUBJECTS = [
    "AI", "Networking", "Security", "Databases",
    "OS", "Hardware", "Software", "Cloud", "IoT", "Robotics"
]

if sys.platform == "win32":
    os.system("color")

class C:
    RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
    YELLOW="\033[93m"; RED="\033[91m"; MAGENTA="\033[95m"; BLUE="\033[94m"
    WHITE="\033[97m"; GREY="\033[90m"

session = {
    "name": None, "ip": None, "server_ip": None,
    "subjects": [], "registered": False, "rq": 1,
}
rq_lock = threading.Lock()
inbox      = []
inbox_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def ok(msg):
    print(f"{C.GREEN}[OK]  {msg}{C.RESET}")

def err(msg):
    print(f"{C.RED}[ERR] {msg}{C.RESET}")

def info(msg):
    print(f"{C.GREY}[..] {msg}{C.RESET}")

def q(s):
    """Wrap a user string in quotes so multi-word values survive transmission."""
    return f'"{s}"'

def next_rq():
    with rq_lock:
        rq = session["rq"]; session["rq"] += 1
    return rq

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except: return "0.0.0.0"
    finally: s.close()

def parse(raw):
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()

def tcp_send_recv(message):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((session["server_ip"], SERVER_TCP_PORT))
        info(f"Sent -> {message}")
        sock.send(message.encode())
        resp = sock.recv(65535).decode().strip()
        info(f"Recv <- {resp}")
        return resp
    except socket.timeout:         err("Timed out.");          return None
    except ConnectionRefusedError: err("Connection refused.");  return None
    except Exception as e:         err(f"TCP error: {e}");     return None
    finally: sock.close()

def udp_send(message):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(message.encode(), (session["server_ip"], SERVER_UDP_PORT))
        s.close()
        info(f"UDP -> {message}")
    except Exception as e:
        err(f"UDP error: {e}")


# ── Real-time UDP listener ────────────────────────────────────────────────────

def start_udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", CLIENT_UDP_PORT))
    except OSError as e:
        err(f"Cannot bind UDP port {CLIENT_UDP_PORT}: {e}"); return

    while True:
        try:
            data, _ = sock.recvfrom(65535)
            raw   = data.decode().strip()
            parts = parse(raw)
            now   = ts()

            if parts[0] == "MESSAGE" and len(parts) >= 5:
                # MESSAGE Name Subject "Title" "Text"
                name, subject, title, text = parts[1], parts[2], parts[3], parts[4]
                with inbox_lock:
                    inbox.append({"sender": name, "subject": subject,
                                  "title": title, "text": text, "time": now})
                    idx = len(inbox)
                print(f"\n{C.MAGENTA}-------- NEWS #{idx} [{now}] --------{C.RESET}")
                print(f"{C.MAGENTA}Subject : {subject}{C.RESET}")
                print(f"{C.MAGENTA}From    : {name}{C.RESET}")
                print(f"{C.MAGENTA}Title   : {title}{C.RESET}")
                print(f"{C.MAGENTA}         {text}{C.RESET}")
                print(f"{C.MAGENTA}[Pick option 6 then #{idx} to comment]{C.RESET}")
                print(f"{C.MAGENTA}--------------------------------{C.RESET}\n")

            elif parts[0] == "COMMENT" and len(parts) >= 5:
                # COMMENT Name Subject "Title" "Text"
                name, subject, title, text = parts[1], parts[2], parts[3], parts[4]
                print(f"\n{C.BLUE}-------- COMMENT [{now}] --------{C.RESET}")
                print(f"{C.BLUE}On   : {title} [{subject}]{C.RESET}")
                print(f"{C.BLUE}From : {name}{C.RESET}")
                print(f"{C.BLUE}      {text}{C.RESET}")
                print(f"{C.BLUE}----------------------------------{C.RESET}\n")

        except Exception as e:
            err(f"Listener error: {e}")


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover_servers():
    found = []
    sock  = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(DISCOVERY_TIMEOUT)
    try:
        sock.sendto(DISCOVERY_MSG.encode(), ("<broadcast>", SERVER_UDP_PORT))
        info(f"Scanning ({DISCOVERY_TIMEOUT}s)...")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                parts = data.decode().strip().split()
                if len(parts) == 2 and parts[0] == "NSS_SERVER":
                    ip, name = addr[0], parts[1]
                    if ip not in [s[0] for s in found]:
                        found.append((ip, name))
                        info(f"Found: {name} @ {ip}")
            except socket.timeout:
                break
    finally:
        sock.close()
    return found


# ── 1. Register ───────────────────────────────────────────────────────────────

def register():
    servers = discover_servers()
    if not servers:
        err("No servers found."); return

    print("\nAvailable servers:")
    for i, (ip, name) in enumerate(servers, 1):
        print(f"  {i}. {name} ({ip})")

    choice = input("Pick server: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(servers)):
        err("Invalid choice."); return
    session["server_ip"] = servers[int(choice) - 1][0]

    name = input("Username: ").strip()
    if not name:
        err("Username cannot be empty."); return

    for attempt in range(1, MAX_RETRIES + 1):
        resp = tcp_send_recv(
            f"REGISTER {next_rq()} {name} {session['ip']} {CLIENT_TCP_PORT} {CLIENT_UDP_PORT}"
        )
        if not resp: break
        parts = resp.split()
        if parts[0] == "REGISTERED":
            session["name"] = name; session["registered"] = True
            ok(f"Registered as '{name}'."); return
        elif parts[0] == "REGISTER-DENIED":
            err(f"Denied: {' '.join(parts[2:])}")
            if attempt < MAX_RETRIES:
                info(f"Retrying in {RETRY_DELAY}s..."); time.sleep(RETRY_DELAY)
        else:
            err(f"Unexpected: {resp}"); break
    err("Registration failed.")


# ── 2. Deregister ─────────────────────────────────────────────────────────────

def deregister():
    if not session["registered"]: err("Not registered."); return
    if input(f"Deregister '{session['name']}'? (yes/no): ").strip().lower() != "yes":
        info("Cancelled."); return
    tcp_send_recv(f"DE-REGISTER {next_rq()} {session['name']}")
    session["registered"] = False; session["name"] = None
    ok("Deregistered.")


# ── 3. Update info ────────────────────────────────────────────────────────────

def update_info():
    if not session["registered"]: err("Not registered."); return
    info(f"Current IP: {session['ip']}  TCP:{CLIENT_TCP_PORT}  UDP:{CLIENT_UDP_PORT}")
    new_ip = input("New IP (blank = keep): ").strip() or session["ip"]
    resp = tcp_send_recv(
        f"UPDATE {next_rq()} {session['name']} {new_ip} {CLIENT_TCP_PORT} {CLIENT_UDP_PORT}"
    )
    if resp and resp.startswith("UPDATE-CONFIRMED"):
        session["ip"] = new_ip; ok("Info updated.")
    else:
        err(f"Update failed: {resp}")


# ── 4. Update subjects ────────────────────────────────────────────────────────

def update_subjects():
    if not session["registered"]: err("Not registered."); return
    info(f"Current: {', '.join(session['subjects']) or 'none'}")
    print("\nAvailable subjects:")
    for i, s in enumerate(VALID_SUBJECTS, 1):
        print(f"  {i}. {s}")
    raw = input("Enter numbers (e.g. 1 3 5): ").strip()
    try:
        indices = [int(x) for x in raw.split()]
        if not indices or not all(1 <= i <= len(VALID_SUBJECTS) for i in indices):
            raise ValueError
        subs = [VALID_SUBJECTS[i - 1] for i in indices]
    except ValueError:
        err("Invalid input."); return
    resp = tcp_send_recv(f"SUBJECTS {next_rq()} {session['name']} {' '.join(subs)}")
    if resp and resp.startswith("SUBJECTS-UPDATED"):
        session["subjects"] = subs; ok(f"Subjects: {', '.join(subs)}")
    else:
        err(f"Rejected: {resp}")


# ── 5. Publish ────────────────────────────────────────────────────────────────

def publish():
    if not session["registered"]: err("Not registered."); return
    if not session["subjects"]:   err("Set subjects first (option 4)."); return

    print("\nYour subjects:")
    for i, s in enumerate(session["subjects"], 1):
        print(f"  {i}. {s}")
    choice = input("Pick subject: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(session["subjects"])):
        err("Invalid choice."); return
    subject = session["subjects"][int(choice) - 1]

    title = input("Title: ").strip()
    text  = input("Text : ").strip()

    # q() wraps in quotes so multi-word values are kept as one token
    resp = tcp_send_recv(
        f"PUBLISH {next_rq()} {session['name']} {subject} {q(title)} {q(text)}"
    )
    if resp and resp.startswith("PUBLISH-DENIED"):
        err(f"Denied: {' '.join(resp.split()[2:])}")
    else:
        ok("Message published.")


# ── 6. Comment ────────────────────────────────────────────────────────────────

def comment():
    if not session["registered"]: err("Not registered."); return

    with inbox_lock:
        snap = list(inbox)

    if snap:
        print("\nReceived messages (pick one to comment on, or 0 for manual):")
        for i, m in enumerate(snap, 1):
            print(f"  {i}. [{m['subject']}] \"{m['title']}\" — from {m['sender']} at {m['time']}")
        print("  0. Enter manually")
        choice = input("Pick: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(snap):
            selected = snap[int(choice) - 1]
            subject  = selected["subject"]
            title    = selected["title"]
            print(f"\nCommenting on: [{subject}] \"{title}\"")
            text = input("Your comment: ").strip()
            udp_send(f"PUBLISH-COMMENT {session['name']} {subject} {q(title)} {q(text)}")
            ok("Comment sent."); return
        elif choice != "0":
            err("Invalid choice."); return

    # Manual entry
    subj_list = session["subjects"] if session["subjects"] else VALID_SUBJECTS
    print("\nSubjects:")
    for i, s in enumerate(subj_list, 1):
        print(f"  {i}. {s}")
    choice = input("Pick subject: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(subj_list)):
        err("Invalid choice."); return
    subject = subj_list[int(choice) - 1]
    title   = input("Title of original: ").strip()
    text    = input("Your comment     : ").strip()
    udp_send(f"PUBLISH-COMMENT {session['name']} {subject} {q(title)} {q(text)}")
    ok("Comment sent.")


# ── Menu ──────────────────────────────────────────────────────────────────────

def print_menu():
    if session["registered"]:
        subs = ', '.join(session['subjects']) or 'no subjects'
        print(f"\n{C.GREEN}Logged in as: {session['name']} @ {session['server_ip']} [{subs}]{C.RESET}")
        with inbox_lock:
            count = len(inbox)
        if count:
            print(f"{C.YELLOW}  Inbox: {count} message(s){C.RESET}")
    else:
        print(f"\n{C.RED}Not registered{C.RESET}")
    print("---------------------------")
    print("1. Register")
    print("2. Deregister")
    print("3. Update Info")
    print("4. Update Subjects")
    print("5. Publish Message")
    print("6. Comment on Message")
    print("0. Exit")
    print("---------------------------")


def main():
    session["ip"] = get_local_ip()
    print(f"NSS Client | IP: {session['ip']} | TCP:{CLIENT_TCP_PORT} UDP:{CLIENT_UDP_PORT}")
    threading.Thread(target=start_udp_listener, daemon=True).start()
    while True:
        print_menu()
        choice = input("Choice: ").strip()
        if   choice == "1": register()
        elif choice == "2": deregister()
        elif choice == "3": update_info()
        elif choice == "4": update_subjects()
        elif choice == "5": publish()
        elif choice == "6": comment()
        elif choice == "0": print("Goodbye."); break
        else: err("Invalid choice.")

if __name__ == "__main__":
    main()
