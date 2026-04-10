import { useContext } from "react";

import { VoiceChessContext } from "../providers/VoiceChessProvider";

export function useVoiceChessSession() {
  const value = useContext(VoiceChessContext);
  if (!value) {
    throw new Error("useVoiceChessSession must be used within a VoiceChessProvider.");
  }
  return value;
}
