from pydantic import BaseModel, Field


class DocumentCreateRequest(BaseModel):
    id: str = Field(..., min_length=1)
    html: str = Field(..., min_length=1)


class DocumentCreateResponse(BaseModel):
    id: str
    title: str


class SearchResult(BaseModel):
    id: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)


class ToolTrace(BaseModel):
    tool_name: str
    arguments: dict[str, str] = Field(default_factory=dict)
    status: str
    output_preview: str = ""


class ChatHistoryTurn(BaseModel):
    role: str
    content: str
    consulted_files: list[str] = Field(default_factory=list)
    tool_calls: list[ToolTrace] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    tool_calls: list[ToolTrace] = Field(default_factory=list)
    consulted_files: list[str] = Field(default_factory=list)
    history: list[ChatHistoryTurn] = Field(default_factory=list)


class SessionHistoryResponse(BaseModel):
    session_id: str
    history: list[ChatHistoryTurn] = Field(default_factory=list)
