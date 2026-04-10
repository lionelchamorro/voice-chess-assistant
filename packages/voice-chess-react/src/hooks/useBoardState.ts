import { useVoiceChessSession } from "./useVoiceChessSession";

export function useBoardState() {
  return useVoiceChessSession().boardState;
}
