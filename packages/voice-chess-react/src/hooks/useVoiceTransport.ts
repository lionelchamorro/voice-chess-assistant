import { useEffect, useEffectEvent, useRef, useState } from "react";

import type { MicrophonePermissionStatus, VoiceConnectionStatus } from "../types";

const DEFAULT_ICE_SERVERS: RTCIceServer[] = [{ urls: "stun:stun.l.google.com:19302" }];
const ICE_GATHERING_TIMEOUT_MS = 4000;
// With non-trickle signaling, waiting for the "complete" gathering state can
// stall for seconds while STUN queries settle (especially on localhost, where
// host candidates arrive instantly and are enough). Send the offer a short
// grace period after the first candidate instead.
const ICE_FIRST_CANDIDATE_GRACE_MS = 500;

interface UseVoiceTransportOptions {
  sessionId: string;
  signalingApiUrl: string | null;
  iceServers?: RTCIceServer[] | undefined;
  onError: (message: string | null) => void;
}

interface OfferResponse {
  sessionId: string;
  sdp: string;
  type: string;
  pcId: string;
}

interface VoiceStatusResponse {
  available: boolean;
  reason?: string | null;
}

export function useVoiceTransport({
  sessionId,
  signalingApiUrl,
  iceServers = DEFAULT_ICE_SERVERS,
  onError,
}: UseVoiceTransportOptions) {
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteStreamRef = useRef<MediaStream | null>(null);
  const [voiceConnectionStatus, setVoiceConnectionStatus] = useState<VoiceConnectionStatus>("idle");
  const [microphonePermissionStatus, setMicrophonePermissionStatus] =
    useState<MicrophonePermissionStatus>("unknown");
  const [remoteAudioStream, setRemoteAudioStream] = useState<MediaStream | null>(null);
  const [voiceTransportAvailable, setVoiceTransportAvailable] = useState(true);
  const [voiceTransportReason, setVoiceTransportReason] = useState<string | null>(null);

  const handleError = useEffectEvent(onError);

  const disconnectVoice = useEffectEvent(() => {
    peerConnectionRef.current?.close();
    peerConnectionRef.current = null;

    stopStream(localStreamRef.current);
    stopStream(remoteStreamRef.current);
    localStreamRef.current = null;
    remoteStreamRef.current = null;

    setRemoteAudioStream(null);
    setVoiceConnectionStatus("idle");
  });

  const connectVoice = useEffectEvent(async () => {
    if (peerConnectionRef.current) {
      return;
    }

    if (!signalingApiUrl) {
      setVoiceConnectionStatus("error");
      handleError("Voice signaling URL is not configured.");
      return;
    }

    if (!voiceTransportAvailable) {
      setVoiceConnectionStatus("error");
      handleError(voiceTransportReason ?? "Voice transport is not available on this server.");
      return;
    }

    try {
      setVoiceConnectionStatus("requesting_media");
      handleError(null);

      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      localStreamRef.current = localStream;
      setMicrophonePermissionStatus("granted");

      const remoteStream = new MediaStream();
      remoteStreamRef.current = remoteStream;
      setRemoteAudioStream(remoteStream);

      const peerConnection = new RTCPeerConnection({ iceServers });
      peerConnectionRef.current = peerConnection;

      for (const track of localStream.getAudioTracks()) {
        peerConnection.addTrack(track, localStream);
      }

      peerConnection.ontrack = (event) => {
        const currentRemoteStream = remoteStreamRef.current;
        if (!currentRemoteStream) {
          return;
        }
        const tracks = event.streams[0]?.getTracks() ?? [event.track];
        for (const track of tracks) {
          if (!currentRemoteStream.getTracks().some((currentTrack) => currentTrack.id === track.id)) {
            currentRemoteStream.addTrack(track);
          }
        }
      };

      peerConnection.onconnectionstatechange = () => {
        if (peerConnection.connectionState === "connected") {
          setVoiceConnectionStatus("connected");
          handleError(null);
        }
        if (peerConnection.connectionState === "disconnected" || peerConnection.connectionState === "closed") {
          setVoiceConnectionStatus("idle");
        }
        if (peerConnection.connectionState === "failed") {
          setVoiceConnectionStatus("error");
          handleError("Voice transport connection failed.");
        }
      };

      peerConnection.oniceconnectionstatechange = () => {
        if (peerConnection.iceConnectionState === "failed") {
          setVoiceConnectionStatus("error");
          handleError("Voice ICE negotiation failed.");
        }
      };

      setVoiceConnectionStatus("connecting");
      const offer = await peerConnection.createOffer();
      await peerConnection.setLocalDescription(offer);
      await waitForIceGatheringComplete(peerConnection, ICE_GATHERING_TIMEOUT_MS);
      if (!peerConnection.localDescription?.sdp || !peerConnection.localDescription.type) {
        throw new Error("WebRTC offer negotiation did not produce a local description.");
      }

      const response = await fetch(`${signalingApiUrl.replace(/\/$/, "")}/api/offer`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sessionId,
          sdp: peerConnection.localDescription.sdp,
          type: peerConnection.localDescription.type,
        }),
      });

      if (!response.ok) {
        throw new Error(await buildSignalingError(response));
      }

      const answer = (await response.json()) as OfferResponse;
      await peerConnection.setRemoteDescription(
        new RTCSessionDescription({
          type: answer.type as RTCSdpType,
          sdp: answer.sdp,
        }),
      );
      setVoiceConnectionStatus("connected");
    } catch (error) {
      if (isPermissionError(error)) {
        setMicrophonePermissionStatus("denied");
      }
      disconnectVoice();
      setVoiceConnectionStatus("error");
      handleError(error instanceof Error ? error.message : "Unable to start voice transport.");
    }
  });

  useEffect(() => {
    if (!signalingApiUrl) {
      setVoiceTransportAvailable(false);
      setVoiceTransportReason("Voice signaling URL is not configured.");
      return;
    }

    let disposed = false;
    void fetch(`${signalingApiUrl.replace(/\/$/, "")}/api/voice-status`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await buildSignalingError(response));
        }
        return (await response.json()) as VoiceStatusResponse;
      })
      .then((status) => {
        if (disposed) {
          return;
        }
        setVoiceTransportAvailable(status.available);
        setVoiceTransportReason(status.reason ?? null);
      })
      .catch((error: unknown) => {
        if (disposed) {
          return;
        }
        setVoiceTransportAvailable(false);
        setVoiceTransportReason(
          error instanceof Error ? error.message : "Unable to verify voice transport availability.",
        );
      });

    return () => {
      disposed = true;
    };
  }, [signalingApiUrl]);

  useEffect(() => {
    return () => {
      disconnectVoice();
    };
  }, []);

  return {
    voiceConnectionStatus,
    voiceTransportAvailable,
    voiceTransportReason,
    microphonePermissionStatus,
    remoteAudioStream,
    connectVoice,
    disconnectVoice,
  };
}

function stopStream(stream: MediaStream | null) {
  for (const track of stream?.getTracks() ?? []) {
    track.stop();
  }
}

function waitForIceGatheringComplete(peerConnection: RTCPeerConnection, timeoutMs: number) {
  if (peerConnection.iceGatheringState === "complete") {
    return Promise.resolve();
  }

  return new Promise<void>((resolve) => {
    let timeoutId: ReturnType<typeof setTimeout>;
    let graceId: ReturnType<typeof setTimeout> | null = null;

    const finish = () => {
      peerConnection.removeEventListener("icegatheringstatechange", handleStateChange);
      peerConnection.removeEventListener("icecandidate", handleCandidate);
      clearTimeout(timeoutId);
      if (graceId !== null) {
        clearTimeout(graceId);
      }
      resolve();
    };

    const handleStateChange = () => {
      if (peerConnection.iceGatheringState === "complete") {
        finish();
      }
    };

    const handleCandidate = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate && graceId === null) {
        graceId = setTimeout(finish, ICE_FIRST_CANDIDATE_GRACE_MS);
      }
    };

    peerConnection.addEventListener("icegatheringstatechange", handleStateChange);
    peerConnection.addEventListener("icecandidate", handleCandidate);
    // Trickle-less signaling still works with a partial candidate set, so a
    // stalled gatherer (e.g. no STUN/TURN reachable) must not block forever.
    timeoutId = setTimeout(finish, timeoutMs);
  });
}

function isPermissionError(error: unknown) {
  if (!(error instanceof DOMException)) {
    return false;
  }
  return error.name === "NotAllowedError" || error.name === "PermissionDeniedError";
}

async function buildSignalingError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) {
      return payload.detail;
    }
  } catch {
    // Fall back to the status code when the body is not JSON.
  }
  return `Voice signaling request failed with status ${response.status}.`;
}
