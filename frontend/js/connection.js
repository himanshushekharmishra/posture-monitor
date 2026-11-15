// WebSocket client for /ws with automatic reconnects.
// Message formats are documented in backend/protocol.py.

const MAX_BACKOFF_MS = 10_000;

export class PostureSocket {
  /**
   * @param {(msg: object) => void} onMessage  every message from the server
   * @param {(status: "connecting" | "online" | "offline") => void} onStatus
   */
  constructor(onMessage, onStatus) {
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.backoff = 500;
    this.ws = null;
  }

  get url() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${location.host}/ws`;
  }

  get isOpen() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** Open the socket; call once after construction. Reconnects by itself after that. */
  connect() {
    this.onStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.addEventListener("open", () => {
      this.backoff = 500;
      this.onStatus("online");
    });
    ws.addEventListener("message", (e) => {
      try {
        this.onMessage(JSON.parse(e.data));
      } catch (err) {
        console.error("Bad message from server", err);
      }
    });
    ws.addEventListener("close", (e) => {
      if (e.code === 4401) {
        // Logged out, session expired or trial over: reconnecting won't help.
        this.onStatus("unauthorized");
        return;
      }
      this.onStatus("offline");
      setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    });
  }

  /** Send a message; silently dropped while disconnected (frames are disposable). */
  send(message) {
    if (this.isOpen) this.ws.send(JSON.stringify(message));
  }
}
