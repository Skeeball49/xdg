"""
NSS Server — Full Implementation
Protocol: flat text, fields separated by spaces.
Multi-word fields (title, text) are quoted by the client.
Server parses with shlex to handle quoted strings.

Message formats:
  TCP:
    REGISTER   RQ# Name IP TCP# UDP#
    DE-REGISTER RQ# Name
    UPDATE     RQ# Name IP TCP# UDP#
    SUBJECTS   RQ# Name subj1 subj2 ...
    PUBLISH    RQ# Name Subject "Title" "Text"

  UDP client→server:
    PUBLISH-COMMENT Name Subject "Title" "Text"

  UDP server→server:
    FORWARD         Name Subject "Title" "Text"
    FORWARD-COMMENT Name Subject "Title" "Text"

  UDP server→client:
    MESSAGE Name Subject "Title" "Text"
    COMMENT Name Subject "Title" "Text"
"""

import socket
import threading
import json
import os
import shlex
from datetime import datetime

SERVER_NAME = "Server-A"   # Change to "Server-B" on the second machine

TCP_PORT  = 10000
UDP_PORT  = 20000
MAX_USERS = 100

VALID_SUBJECTS = {
    "AI", "Networking", "Security", "Databases",
    "OS", "Hardware", "Software", "Cloud", "IoT", "Robotics"
}

STORAGE_FILE     = f"users_{SERVER_NAME}.json"
users_lock       = threading.Lock()
peer_server_ip   = None
peer_server_lock = threading.Lock()


class C:
    RESET="\033[0m"; BOLD="\033[1m"; CYAN="\033[96m"; GREEN="\033[92m"
    YELLOW="\033[93m"; RED="\033[91m"; MAGENTA="\033[95m"; BLUE="\033[94m"
    WHITE="\033[97m"; GREY="\033[90m"

TAG_COLORS = {
    "DISCOVERY": C.CYAN,   "REGISTRATION": C.GREEN, "DEREGISTER": C.RED,
    "UPDATE":    C.YELLOW, "SUBJECTS":     C.YELLOW, "PUBLISH":   C.MAGENTA,
    "MSG":       C.MAGENTA,"COMMENT":      C.BLUE,   "PEER":      C.WHITE,
    "TCP":       C.GREY,   "UDP":          C.GREY,
}

def _log(tag, msg, ok=None):
    now = datetime.now().strftime("%H:%M:%S")
    col = TAG_COLORS.get(tag, C.RESET)
    ind = f"{C.GREEN}✔{C.RESET} " if ok is True else f"{C.RED}✘{C.RESET} " if ok is False else ""
    print(f"{C.GREY}[{now}]{C.RESET} {C.BOLD}{col}[{SERVER_NAME}][{tag}]{C.RESET} {ind}{msg}")

def _banner(msg, color=C.BOLD):
    print(f"\n{color}{'─'*54}\n  {datetime.now().strftime('%H:%M:%S')}  {msg}\n{'─'*54}{C.RESET}")


# ── Persistence ───────────────────────────────────────────────────────────────

def load_users():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    tmp = STORAGE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, STORAGE_FILE)


# ── Encoding helpers ──────────────────────────────────────────────────────────

def quote(s):
    """Wrap a string in quotes for safe transmission."""
    return f'"{s}"'

def build(cmd, *args):
    """Build a message: CMD arg1 arg2 "multi word arg" ..."""
    return (cmd + " " + " ".join(str(a) for a in args)).encode()


# ── UDP helpers ───────────────────────────────────────────────────────────────

def udp_send_raw(ip, port, data: bytes):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(data, (ip, port))
        s.close()
    except Exception as e:
        _log("UDP", f"Send error → {ip}:{port} {e}", ok=False)

def forward_to_peer(data: bytes):
    with peer_server_lock:
        ip = peer_server_ip
    if ip:
        udp_send_raw(ip, UDP_PORT, data)
        _log("PEER", f"Forwarded → {ip}")
    else:
        _log("PEER", "No peer — skipping forward.")


# ── Distribute ────────────────────────────────────────────────────────────────

def distribute_message(name, subject, title, text, registered_users, udp_sock, exclude=None):
    data = build("MESSAGE", name, subject, quote(title), quote(text))
    with users_lock:
        targets = [(u, d) for u, d in registered_users.items()
                   if subject in d.get("subjects", []) and u != exclude]
    if not targets:
        _log("MSG", f"No subscribers for '{subject}'"); return
    for uname, d in targets:
        try:
            udp_sock.sendto(data, (d["ip"], d["udp_socket"]))
            _log("MSG", f"→ {uname}  [{subject}] {title}")
        except Exception as e:
            _log("MSG", f"Error → {uname}: {e}", ok=False)

def distribute_comment(name, subject, title, text, registered_users, udp_sock, exclude=None):
    data = build("COMMENT", name, subject, quote(title), quote(text))
    with users_lock:
        targets = [(u, d) for u, d in registered_users.items()
                   if subject in d.get("subjects", []) and u != exclude]
    if not targets:
        _log("COMMENT", f"No subscribers for '{subject}'"); return
    for uname, d in targets:
        try:
            udp_sock.sendto(data, (d["ip"], d["udp_socket"]))
            _log("COMMENT", f"→ {uname}  [{subject}] {title}")
        except Exception as e:
            _log("COMMENT", f"Error → {uname}: {e}", ok=False)


# ── Parse helper ──────────────────────────────────────────────────────────────

def parse(raw):
    """Parse a message using shlex so quoted strings are kept together."""
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


# ── UDP handler ───────────────────────────────────────────────────────────────

def handle_udp(udp_sock, registered_users):
    global peer_server_ip
    _log("UDP", f"Listening on port {UDP_PORT}...")
    while True:
        try:
            data, addr = udp_sock.recvfrom(65535)
            raw   = data.decode().strip()
            parts = parse(raw)
            if not parts:
                continue
            cmd = parts[0]

            if cmd == "NSS_DISCOVER":
                udp_sock.sendto(f"NSS_SERVER {SERVER_NAME}".encode(), addr)
                _log("DISCOVERY", f"Client {addr[0]} discovered this server")

            elif cmd == "NSS_SERVER":
                peer_name = parts[1] if len(parts) > 1 else ""
                if peer_name != SERVER_NAME:
                    with peer_server_lock:
                        peer_server_ip = addr[0]
                    _log("PEER", f"Peer '{peer_name}' at {addr[0]}", ok=True)

            elif cmd == "PUBLISH-COMMENT" and len(parts) >= 5:
                # PUBLISH-COMMENT Name Subject "Title" "Text"
                name, subject, title, text = parts[1], parts[2], parts[3], parts[4]
                _banner(f"COMMENT by {name} [{subject}] \"{title}\"", C.BLUE)
                distribute_comment(name, subject, title, text, registered_users, udp_sock, exclude=name)
                forward_to_peer(data)   # forward raw bytes to peer as FORWARD-COMMENT
                # Rebuild as FORWARD-COMMENT so peer doesn't re-forward
                fwd = build("FORWARD-COMMENT", name, subject, quote(title), quote(text))
                forward_to_peer(fwd)

            elif cmd == "FORWARD" and len(parts) >= 5:
                # FORWARD Name Subject "Title" "Text"
                name, subject, title, text = parts[1], parts[2], parts[3], parts[4]
                _banner(f"FORWARDED by {name} [{subject}] \"{title}\"", C.WHITE)
                distribute_message(name, subject, title, text, registered_users, udp_sock, exclude=name)

            elif cmd == "FORWARD-COMMENT" and len(parts) >= 5:
                name, subject, title, text = parts[1], parts[2], parts[3], parts[4]
                _banner(f"FORWARDED COMMENT by {name} [{subject}]", C.BLUE)
                distribute_comment(name, subject, title, text, registered_users, udp_sock, exclude=name)
                # Do NOT re-forward

        except Exception as e:
            _log("UDP", f"Error: {e}", ok=False)


# ── TCP dispatcher ────────────────────────────────────────────────────────────

def handle_tcp(conn, addr, registered_users, udp_sock):
    try:
        raw = conn.recv(65535).decode().strip()
        if not raw: return
        parts = parse(raw)
        if not parts: return
        cmd = parts[0]
        _log("TCP", f"From {addr[0]}  cmd={cmd}")

        if   cmd == "REGISTER":    do_register(conn, parts, registered_users)
        elif cmd == "DE-REGISTER": do_deregister(conn, parts, registered_users)
        elif cmd == "UPDATE":      do_update(conn, parts, registered_users)
        elif cmd == "SUBJECTS":    do_subjects(conn, parts, registered_users)
        elif cmd == "PUBLISH":     do_publish(conn, parts, registered_users, udp_sock)
        else:
            conn.send(f"ERROR Unknown command: {cmd}".encode())
    except Exception as e:
        _log("TCP", f"Error: {e}", ok=False)
    finally:
        conn.close()


# ── Handlers ──────────────────────────────────────────────────────────────────

def do_register(conn, parts, users):
    # REGISTER RQ# Name IP TCP# UDP#
    if len(parts) != 6:
        conn.send(b"REGISTER-DENIED 0 Invalid format"); return
    _, rq, name, ip, tcp_s, udp_s = parts
    try:
        tcp = int(tcp_s); udp = int(udp_s)
        assert 1024 <= tcp <= 65535 and 1024 <= udp <= 65535
    except (ValueError, AssertionError):
        conn.send(f"REGISTER-DENIED {rq} Invalid socket number".encode()); return
    with users_lock:
        if len(users) >= MAX_USERS:
            conn.send(f"REGISTER-DENIED {rq} Server is full".encode()); return
        if name in users:
            conn.send(f"REGISTER-DENIED {rq} Name already in use".encode()); return
        users[name] = {"ip": ip, "tcp_socket": tcp, "udp_socket": udp, "subjects": []}
        save_users(users)
        total = len(users)
    conn.send(f"REGISTERED {rq}".encode())
    _log("REGISTRATION", f"'{name}' IP={ip} [{total} users]", ok=True)

def do_deregister(conn, parts, users):
    # DE-REGISTER RQ# Name
    if len(parts) < 3: return
    name = parts[2]
    with users_lock:
        if name in users:
            del users[name]; save_users(users)
            _log("DEREGISTER", f"'{name}' removed [{len(users)} left]", ok=True)
        else:
            _log("DEREGISTER", f"'{name}' not found — ignored")

def do_update(conn, parts, users):
    # UPDATE RQ# Name IP TCP# UDP#
    if len(parts) != 6:
        conn.send(b"UPDATE-DENIED 0 Invalid format"); return
    _, rq, name, ip, tcp_s, udp_s = parts
    try:
        tcp = int(tcp_s); udp = int(udp_s)
        assert 1024 <= tcp <= 65535 and 1024 <= udp <= 65535
    except (ValueError, AssertionError):
        conn.send(f"UPDATE-DENIED {rq} Invalid socket number".encode()); return
    with users_lock:
        if name not in users:
            conn.send(f"UPDATE-DENIED {rq} Name not registered".encode()); return
        users[name].update({"ip": ip, "tcp_socket": tcp, "udp_socket": udp})
        save_users(users)
    conn.send(f"UPDATE-CONFIRMED {rq} {name} {ip} {tcp} {udp}".encode())
    _log("UPDATE", f"'{name}' → IP={ip}", ok=True)

def do_subjects(conn, parts, users):
    # SUBJECTS RQ# Name subj1 subj2 ...
    if len(parts) < 4:
        conn.send(b"SUBJECTS-REJECTED 0 Unknown Invalid format"); return
    rq, name, subs = parts[1], parts[2], parts[3:]
    with users_lock:
        if name not in users:
            conn.send(f"SUBJECTS-REJECTED {rq} {name} Name not registered".encode()); return
        invalid = [s for s in subs if s not in VALID_SUBJECTS]
        if invalid:
            conn.send(f"SUBJECTS-REJECTED {rq} {name} Invalid: {' '.join(invalid)}".encode()); return
        users[name]["subjects"] = subs
        save_users(users)
    conn.send(f"SUBJECTS-UPDATED {rq} {name} {' '.join(subs)}".encode())
    _log("SUBJECTS", f"'{name}' → {subs}", ok=True)

def do_publish(conn, parts, users, udp_sock):
    # PUBLISH RQ# Name Subject "Title" "Text"
    if len(parts) < 6:
        conn.send(b"PUBLISH-DENIED 0 Invalid format"); return
    _, rq, name, subject, title, text = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    with users_lock:
        if name not in users:
            conn.send(f"PUBLISH-DENIED {rq} Name not registered".encode()); return
        user_subs = users[name].get("subjects", [])
    if subject not in user_subs:
        conn.send(f"PUBLISH-DENIED {rq} Subject not in your interest list".encode()); return
    _banner(f"PUBLISH by {name} [{subject}] \"{title}\"", C.MAGENTA)
    distribute_message(name, subject, title, text, users, udp_sock, exclude=name)
    forward_to_peer(build("FORWARD", name, subject, quote(title), quote(text)))
    _log("PUBLISH", f"'{name}' [{subject}] \"{title}\"", ok=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def start_server():
    users = load_users()
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{C.BOLD}{C.CYAN}{'═'*55}")
    print(f"  NSS {SERVER_NAME}  —  {now}")
    print(f"  TCP:{TCP_PORT}  UDP:{UDP_PORT}  Max:{MAX_USERS}")
    print(f"  Subjects: {', '.join(sorted(VALID_SUBJECTS))}")
    print(f"  Users restored: {len(users)}")
    print(f"{'═'*55}{C.RESET}\n")

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_sock.bind(("", UDP_PORT))
    threading.Thread(target=handle_udp, args=(udp_sock, users), daemon=True).start()

    threading.Timer(1.0, lambda: udp_sock.sendto(
        f"NSS_SERVER {SERVER_NAME}".encode(), ("<broadcast>", UDP_PORT)
    )).start()

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_sock.bind(("", TCP_PORT))
    tcp_sock.listen(10)
    _log("TCP", f"Listening on port {TCP_PORT} — ready.\n")

    try:
        while True:
            conn, addr = tcp_sock.accept()
            threading.Thread(target=handle_tcp, args=(conn, addr, users, udp_sock), daemon=True).start()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[{SERVER_NAME}] Shutting down.{C.RESET}")
    finally:
        tcp_sock.close(); udp_sock.close()

if __name__ == "__main__":
    start_server()
