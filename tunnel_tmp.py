"""SSH port-forward tunnel: local 8080 -> pod:80 (frontend), 8081 -> pod:3001 (Grafana)."""
import paramiko, socket, threading, select, sys

HOST, PORT, USER, PWD = "172.23.255.8", 31877, "root", "tr88FFAe"
FORWARDS = [("8080", "127.0.0.1", 80), ("8081", "127.0.0.1", 3001)]

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=20)
print("connected", flush=True)


def handler(local_sock, remote_host, remote_port):
    try:
        transport = cli.get_transport()
        chan = transport.open_channel("direct-tcpip", (remote_host, remote_port), local_sock.getpeername())
    except Exception as e:
        print("channel err", e, flush=True)
        local_sock.close()
        return
    while True:
        try:
            r, _, _ = select.select([local_sock, chan], [], [], 5)
        except Exception:
            break
        if not r:
            continue
        try:
            if local_sock in r:
                data = local_sock.recv(65536)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(65536)
                if not data:
                    break
                local_sock.sendall(data)
        except Exception:
            break
    local_sock.close()
    chan.close()


def serve(port, remote_host, remote_port):
    port, remote_port = int(port), int(remote_port)
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", port))
    ls.listen(5)
    print(f"listening 127.0.0.1:{port} -> {remote_host}:{remote_port}", flush=True)
    while True:
        cs, _ = ls.accept()
        threading.Thread(target=handler, args=(cs, remote_host, remote_port), daemon=True).start()


for lp, rh, rp in FORWARDS:
    threading.Thread(target=serve, args=(lp, rh, rp), daemon=True).start()

threading.Event().wait()
