import type { VoiceChessClientCommand, VoiceChessServerEvent } from "@voice-chess/core";
import {
  useEffectEvent,
  useRef,
  useState,
} from "react";

import type { ConnectionStatus } from "../types";

const RECONNECT_BASE_DELAY_MS = 500;
const RECONNECT_MAX_DELAY_MS = 8000;

interface UseBoardSocketOptions {
  boardSocketUrl: string;
  sessionId: string;
  onEvent: (event: VoiceChessServerEvent) => void;
  onError: (message: string) => void;
}

export function useBoardSocket({
  boardSocketUrl,
  sessionId,
  onEvent,
  onError,
}: UseBoardSocketOptions) {
  const socketRef = useRef<WebSocket | null>(null);
  const shouldReconnectRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");

  const handleEvent = useEffectEvent(onEvent);
  const handleError = useEffectEvent(onError);

  const clearReconnectTimer = useEffectEvent(() => {
    if (reconnectTimeoutRef.current !== null) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  });

  const openSocket = useEffectEvent(() => {
    setConnectionStatus("connecting");
    const socket = new WebSocket(`${boardSocketUrl.replace(/\/$/, "")}/${sessionId}/board`);
    socketRef.current = socket;

    socket.onopen = () => {
      reconnectAttemptRef.current = 0;
      setConnectionStatus("connected");
    };
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data) as VoiceChessServerEvent;
      handleEvent(payload);
    };
    socket.onerror = () => {
      setConnectionStatus("error");
      handleError("Board WebSocket connection failed.");
    };
    socket.onclose = () => {
      socketRef.current = null;
      if (!shouldReconnectRef.current) {
        setConnectionStatus("idle");
        return;
      }
      setConnectionStatus("connecting");
      const attempt = reconnectAttemptRef.current + 1;
      reconnectAttemptRef.current = attempt;
      const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** (attempt - 1), RECONNECT_MAX_DELAY_MS);
      reconnectTimeoutRef.current = setTimeout(() => {
        if (shouldReconnectRef.current) {
          openSocket();
        }
      }, delay);
    };
  });

  const connect = useEffectEvent(async () => {
    shouldReconnectRef.current = true;
    if (socketRef.current) {
      return;
    }
    clearReconnectTimer();
    reconnectAttemptRef.current = 0;
    openSocket();
  });

  const disconnect = useEffectEvent(() => {
    shouldReconnectRef.current = false;
    clearReconnectTimer();
    socketRef.current?.close();
    socketRef.current = null;
    setConnectionStatus("idle");
  });

  const sendCommand = useEffectEvent((command: VoiceChessClientCommand) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      handleError("Cannot send command while the board socket is disconnected.");
      return;
    }
    socketRef.current.send(JSON.stringify(command));
  });

  return {
    connectionStatus,
    connect,
    disconnect,
    sendCommand,
  };
}
