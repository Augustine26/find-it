"""One FindIt at a time: a second launch (right-click menu, shortcut, hotkey) just hands over to the running one."""
import socket, threading, json

PORT = 48731
HELLO = "findit-ok"


def send(msg, timeout=0.5):
    """give msg (dict) to a running FindIt. True if one answered."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            return s.recv(64).decode("utf-8", "ignore").strip() == HELLO
    except OSError:
        return False


class Server:
    def __init__(self, callback):
        self.callback = callback
        self.sock = None

    def start(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):          # Windows: nobody else may share the port
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", PORT))
            s.listen(4)
        except OSError:
            return False
        self.sock = s
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        while self.sock:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            try:
                c.settimeout(1)
                data = c.recv(8192).decode("utf-8", "ignore").strip()
                msg = json.loads(data) if data else {}
                c.sendall((HELLO + "\n").encode())
                if isinstance(msg, dict):
                    self.callback(msg)
            except Exception:
                pass
            finally:
                try:
                    c.close()
                except OSError:
                    pass

    def stop(self):
        s, self.sock = self.sock, None
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
