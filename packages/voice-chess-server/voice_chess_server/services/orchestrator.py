"""Pipecat runtime orchestration and tool wiring."""

from __future__ import annotations

from typing import Any

import structlog

from voice_chess_server.core.config import Settings
from voice_chess_server.schemas.protocol import BoardAnnotation, BoardHighlight
from voice_chess_server.services.session_manager import SessionManager
from voice_chess_server.services.signaling import SignalingRuntimeError

log = structlog.get_logger()


class BotOrchestrator:
    """Run the voice pipeline for a negotiated transport."""

    def __init__(self, settings: Settings, session_manager: SessionManager) -> None:
        self._settings = settings
        self._session_manager = session_manager

    async def run_transport(self, session_id: str, transport: Any) -> None:
        """Start a Pipecat pipeline for a transport."""

        runtime = self._load_runtime()
        FunctionSchema = runtime["FunctionSchema"]
        ToolsSchema = runtime["ToolsSchema"]
        LLMContext = runtime["LLMContext"]
        LLMContextAggregatorPair = runtime["LLMContextAggregatorPair"]
        LLMUserAggregatorParams = runtime["LLMUserAggregatorParams"]
        LocalSmartTurnAnalyzerV3 = runtime["LocalSmartTurnAnalyzerV3"]
        SileroVADAnalyzer = runtime["SileroVADAnalyzer"]
        VADParams = runtime["VADParams"]
        UserTurnStrategies = runtime["UserTurnStrategies"]
        TurnAnalyzerUserTurnStopStrategy = runtime["TurnAnalyzerUserTurnStopStrategy"]
        Pipeline = runtime["Pipeline"]
        PipelineTask = runtime["PipelineTask"]
        PipelineParams = runtime["PipelineParams"]
        PipelineRunner = runtime["PipelineRunner"]
        LLMRunFrame = runtime["LLMRunFrame"]

        stt = self._build_stt(runtime)
        tts = self._build_tts(runtime)
        llm = self._build_llm(runtime)

        llm.register_function("get_board_state", self._tool_get_board_state(session_id))
        llm.register_function("load_position", self._tool_load_position(session_id))
        llm.register_function("load_pgn", self._tool_load_pgn(session_id))
        llm.register_function("make_move", self._tool_make_move(session_id))
        llm.register_function("reset_board", self._tool_reset_board(session_id))
        llm.register_function("set_highlights", self._tool_set_highlights(session_id))
        llm.register_function("set_annotations", self._tool_set_annotations(session_id))

        tools = ToolsSchema(
            standard_tools=[
                FunctionSchema(
                    name="get_board_state",
                    description="Return the current board state, turn, FEN, PGN and move history.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="load_position",
                    description="Replace the current board with a FEN position.",
                    properties={"fen": {"type": "string", "description": "A valid FEN string."}},
                    required=["fen"],
                ),
                FunctionSchema(
                    name="load_pgn",
                    description="Load a PGN and optionally jump to a specific ply.",
                    properties={
                        "pgn": {"type": "string", "description": "A valid PGN string."},
                        "start_ply": {
                            "type": "integer",
                            "description": "Optional ply to review from after loading the PGN.",
                        },
                    },
                    required=["pgn"],
                ),
                FunctionSchema(
                    name="make_move",
                    description="Apply a legal move to the live board using coordinate squares.",
                    properties={
                        "from_square": {"type": "string", "description": "From square like e2."},
                        "to_square": {"type": "string", "description": "To square like e4."},
                        "promotion": {
                            "type": "string",
                            "enum": ["queen", "rook", "bishop", "knight"],
                            "description": "Promotion piece when needed.",
                        },
                    },
                    required=["from_square", "to_square"],
                ),
                FunctionSchema(
                    name="reset_board",
                    description="Reset the board to the default initial position.",
                    properties={},
                    required=[],
                ),
                FunctionSchema(
                    name="set_highlights",
                    description="Highlight one or more squares on the board.",
                    properties={
                        "squares": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Squares to highlight.",
                        },
                        "color": {
                            "type": "string",
                            "enum": ["green", "yellow", "red", "blue"],
                            "description": "Highlight color.",
                        },
                        "label": {"type": "string", "description": "Optional label."},
                    },
                    required=["squares", "color"],
                ),
                FunctionSchema(
                    name="set_annotations",
                    description="Add board annotations such as comments, arrows or circles.",
                    properties={
                        "annotations": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Annotation payloads.",
                        }
                    },
                    required=["annotations"],
                ),
            ]
        )

        context = LLMContext(
            [{"role": "system", "content": self._settings.system_prompt}],
            tools,
        )
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
                ),
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            ),
        )

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                user_aggregator,
                llm,
                tts,
                transport.output(),
                assistant_aggregator,
            ]
        )
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
                audio_out_sample_rate=24000,
            ),
        )

        @task.rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi) -> None:
            log.info("voice_client_ready", session_id=session_id)
            await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client) -> None:
            log.info("voice_client_connected", session_id=session_id)

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client) -> None:
            log.info("voice_client_disconnected", session_id=session_id)
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)
        await runner.run(task)

    def _build_stt(self, runtime: dict[str, Any]) -> Any:
        if self._settings.stt_provider != "deepgram":
            raise SignalingRuntimeError(f"Unsupported STT provider: {self._settings.stt_provider}")
        DeepgramSTTService = runtime["DeepgramSTTService"]
        if not self._settings.deepgram_api_key:
            raise SignalingRuntimeError("VOICE_CHESS_DEEPGRAM_API_KEY is required.")
        return DeepgramSTTService(api_key=self._settings.deepgram_api_key)

    def _build_tts(self, runtime: dict[str, Any]) -> Any:
        if self._settings.tts_provider == "elevenlabs":
            ElevenLabsTTSService = runtime["ElevenLabsTTSService"]
            if not self._settings.elevenlabs_api_key:
                raise SignalingRuntimeError("VOICE_CHESS_ELEVENLABS_API_KEY is required.")
            return ElevenLabsTTSService(
                api_key=self._settings.elevenlabs_api_key,
                voice_id=self._settings.elevenlabs_voice_id,
            )

        if self._settings.tts_provider == "cartesia":
            CartesiaTTSService = runtime["CartesiaTTSService"]
            if not self._settings.cartesia_api_key:
                raise SignalingRuntimeError("VOICE_CHESS_CARTESIA_API_KEY is required.")
            return CartesiaTTSService(
                api_key=self._settings.cartesia_api_key,
                settings=CartesiaTTSService.Settings(
                    voice=self._settings.cartesia_voice_id,
                    model=self._settings.cartesia_model,
                ),
            )

        raise SignalingRuntimeError(f"Unsupported TTS provider: {self._settings.tts_provider}")

    def _build_llm(self, runtime: dict[str, Any]) -> Any:
        if self._settings.llm_provider != "openai":
            raise SignalingRuntimeError(f"Unsupported LLM provider: {self._settings.llm_provider}")
        OpenAILLMService = runtime["OpenAILLMService"]
        if not self._settings.openai_api_key:
            raise SignalingRuntimeError("VOICE_CHESS_OPENAI_API_KEY is required.")
        return OpenAILLMService(
            api_key=self._settings.openai_api_key,
            model=self._settings.llm_model,
        )

    def _tool_get_board_state(self, session_id: str):
        async def tool(params) -> None:
            snapshot = self._session_manager.get_board_state(session_id)
            await params.result_callback(snapshot.model_dump(by_alias=True, mode="json"))

        return tool

    def _tool_load_position(self, session_id: str):
        async def tool(params) -> None:
            result = await self._session_manager.agent_load_fen(session_id, fen=params.arguments["fen"])
            await params.result_callback(result)

        return tool

    def _tool_load_pgn(self, session_id: str):
        async def tool(params) -> None:
            result = await self._session_manager.agent_load_pgn(
                session_id,
                pgn=params.arguments["pgn"],
                start_ply=params.arguments.get("start_ply"),
            )
            await params.result_callback(result)

        return tool

    def _tool_make_move(self, session_id: str):
        async def tool(params) -> None:
            result = await self._session_manager.agent_apply_move(
                session_id,
                from_square=params.arguments["from_square"],
                to_square=params.arguments["to_square"],
                promotion=params.arguments.get("promotion"),
            )
            await params.result_callback(result)

        return tool

    def _tool_reset_board(self, session_id: str):
        async def tool(params) -> None:
            result = await self._session_manager.agent_reset(session_id)
            await params.result_callback(result)

        return tool

    def _tool_set_highlights(self, session_id: str):
        async def tool(params) -> None:
            squares = params.arguments["squares"]
            color = params.arguments["color"]
            label = params.arguments.get("label")
            result = await self._session_manager.agent_set_highlights(
                session_id,
                [BoardHighlight(id="agent-highlight", squares=squares, color=color, label=label)],
            )
            await params.result_callback(result)

        return tool

    def _tool_set_annotations(self, session_id: str):
        async def tool(params) -> None:
            annotations = [BoardAnnotation(**annotation) for annotation in params.arguments["annotations"]]
            result = await self._session_manager.agent_set_annotations(session_id, annotations)
            await params.result_callback(result)

        return tool

    def _load_runtime(self) -> dict[str, Any]:
        try:
            from pipecat.adapters.schemas.function_schema import FunctionSchema
            from pipecat.adapters.schemas.tools_schema import ToolsSchema
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams
            from pipecat.frames.frames import LLMRunFrame
            from pipecat.pipeline.pipeline import Pipeline
            from pipecat.pipeline.runner import PipelineRunner
            from pipecat.pipeline.task import PipelineParams, PipelineTask
            from pipecat.processors.aggregators.llm_context import LLMContext
            from pipecat.processors.aggregators.llm_response_universal import (
                LLMContextAggregatorPair,
                LLMUserAggregatorParams,
            )
            from pipecat.services.cartesia.tts import CartesiaTTSService
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
            from pipecat.services.openai.llm import OpenAILLMService
            from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
            from pipecat.turns.user_turn_strategies import UserTurnStrategies
        except ImportError as exc:
            raise SignalingRuntimeError(
                "Pipecat voice runtime is not installed. Install the optional `voice` extras."
            ) from exc

        return {
            "CartesiaTTSService": CartesiaTTSService,
            "DeepgramSTTService": DeepgramSTTService,
            "ElevenLabsTTSService": ElevenLabsTTSService,
            "FunctionSchema": FunctionSchema,
            "LLMContext": LLMContext,
            "LLMContextAggregatorPair": LLMContextAggregatorPair,
            "LLMRunFrame": LLMRunFrame,
            "LLMUserAggregatorParams": LLMUserAggregatorParams,
            "LocalSmartTurnAnalyzerV3": LocalSmartTurnAnalyzerV3,
            "OpenAILLMService": OpenAILLMService,
            "Pipeline": Pipeline,
            "PipelineParams": PipelineParams,
            "PipelineRunner": PipelineRunner,
            "PipelineTask": PipelineTask,
            "SileroVADAnalyzer": SileroVADAnalyzer,
            "ToolsSchema": ToolsSchema,
            "TurnAnalyzerUserTurnStopStrategy": TurnAnalyzerUserTurnStopStrategy,
            "UserTurnStrategies": UserTurnStrategies,
            "VADParams": VADParams,
        }
