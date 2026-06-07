/**
 * Bob Manager — WebSocket service.
 * Manages the WebSocket connection to the control plane for live updates.
 */

function getWsUrl() {
  if (process.env.REACT_APP_WS_URL) return process.env.REACT_APP_WS_URL;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

class WebSocketService {
  constructor() {
    this.ws = null;
    this.listeners = {};
    this.reconnectTimeout = null;
    this.isConnected = false;
  }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

    const wsUrl = getWsUrl();
    // Cluster A — /ws/client now requires a valid JWT. The token is
    // attached via subprotocol so it never lands in the URL access log.
    // Falls back to a query param when subprotocols are unavailable.
    const token = localStorage.getItem('bob_token') || '';
    if (!token) {
      console.warn('[WS] No bob_token in localStorage; not connecting');
      this._emit('connection', { status: 'unauthorized' });
      return;
    }
    try {
      this.ws = new WebSocket(`${wsUrl}/ws/client`, [`bob.jwt.${token}`]);
    } catch (e) {
      // Subprotocol path failed (older browser) — fall back to query.
      this.ws = new WebSocket(`${wsUrl}/ws/client?token=${encodeURIComponent(token)}`);
    }

    this.ws.onopen = () => {
      console.log('[WS] Connected to control plane');
      this.isConnected = true;
      this._emit('connection', { status: 'connected' });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this._emit(data.type, data.payload);
        this._emit('message', data);
      } catch (e) {
        console.warn('[WS] Invalid message:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[WS] Disconnected. Reconnecting in 3s…');
      this.isConnected = false;
      this._emit('connection', { status: 'disconnected' });
      this.reconnectTimeout = setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
    };
  }

  disconnect() {
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    if (this.ws) this.ws.close();
    this.isConnected = false;
  }

  on(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
    return () => {
      this.listeners[event] = this.listeners[event].filter((cb) => cb !== callback);
    };
  }

  _emit(event, data) {
    const cbs = this.listeners[event] || [];
    cbs.forEach((cb) => cb(data));
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}

const wsService = new WebSocketService();
export default wsService;
