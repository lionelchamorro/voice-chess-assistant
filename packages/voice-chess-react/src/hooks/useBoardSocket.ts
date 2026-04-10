import type { VoiceChessClientCommand, VoiceChessServerEvent } from "@voice-chess/core";
import {
  useEffectEvent,
  useRef,
  useState,
} from "react";

import type { ConnectionStatus } from "../types";

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
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");

  const handleEvent = useEffectEvent(onEvent);
  const handleError = useEffectEvent(onError);

  const connect = useEffectEvent(async () => {
    if (socketRef.current) {
      return;
    }

    setConnectionStatus("connecting");
    const socket = new WebSocket(`${boardSocketUrl.replace(/\/$/, "")}/${sessionId}/board`);
    socketRef.current = socket;

    socket.onopen = () => {
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
      setConnectionStatus("idle");
    };
  });

  const disconnect = useEffectEvent(() => {
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
