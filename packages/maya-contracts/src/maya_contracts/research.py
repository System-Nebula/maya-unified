"""Research agent API contracts — briefs, plans, reports, and run lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from maya_contracts.common import StrictModel


class ResearchDepth(str, Enum):
    SHALLOW = "shallow"
    DEEP = "deep"


class ResearchSourceKind(str, Enum):
    WEB = "web"
    REDDIT = "reddit"
    LOCAL = "local"
    GRAPH = "graph"


class SubTaskType(str, Enum):
    WEB_SEARCH = "web_search"
    PAGE_FETCH = "page_fetch"
    REDDIT = "reddit"
    FIREFOX_HISTORY = "firefox_history"
    GRAPH_RECALL = "graph_recall"


class ResearchRunStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    FAILED = "failed"


class ReportSectionKind(str, Enum):
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    BENCHMARKS = "benchmarks"
    GAPS = "gaps"
    SUMMARY = "summary"


class SubTask(StrictModel):
    id: str
    type: SubTaskType
    query: str
    source_hint: str = ""
    priority: int = 2
    depends_on: list[str] = []


class ResearchPlan(StrictModel):
    subtasks: list[SubTask]
    rationale: str = ""


class ResearchBrief(StrictModel):
    topic: str
    depth: ResearchDepth = ResearchDepth.SHALLOW
    source_mask: list[ResearchSourceKind] = [
        ResearchSourceKind.WEB,
        ResearchSourceKind.REDDIT,
        ResearchSourceKind.LOCAL,
        ResearchSourceKind.GRAPH,
    ]
    seed_urls: list[str] = []
    prior_research_id: str | None = None
    operator_id: str = "local"
    discord_thread_id: str | None = None


class WebSearchResult(StrictModel):
    url: str
    title: str
    snippet: str
    domain: str
    credibility_score: float = 0.5
    fetched_at: datetime | None = None


class FetchedPage(StrictModel):
    url: str
    title: str
    markdown: str
    content_hash: str
    artifact_key: str | None = None
    credibility_score: float = 0.5
    operator_visited: bool = False
    fetched_at: datetime


class RedditPost(StrictModel):
    id: str
    title: str
    url: str
    score: int
    num_comments: int
    selftext: str = ""
    top_comments: list[str] = []


class SentimentBundle(StrictModel):
    subreddit: str
    query: str
    posts: list[RedditPost]
    sentiment_summary: str
    recurring_themes: list[str]
    notable_quotes: list[str]
    fetched_at: datetime


class OperatorContextItem(StrictModel):
    url: str
    title: str
    description: str = ""
    visit_date: datetime | None = None
    similarity_score: float = 0.0


class OperatorContext(StrictModel):
    query: str
    items: list[OperatorContextItem]


class PriorResearchRef(StrictModel):
    id: str
    title: str
    brief: str
    summary: str
    researched_at: datetime
    similarity_score: float = 0.0


class ReportSection(StrictModel):
    kind: ReportSectionKind
    title: str
    body: str


class CitedSource(StrictModel):
    url: str
    title: str
    credibility_score: float
    snippet: str = ""


class ReportMetadata(StrictModel):
    depth: ResearchDepth
    duration_seconds: float
    source_counts: dict[str, int]
    model_used: str = ""
    delta_mode: bool = False


class ResearchReport(StrictModel):
    title: str
    brief: str
    executive_summary: str
    sections: list[ReportSection]
    sources: list[CitedSource]
    uncovered_aspects: list[str]
    suggested_followups: list[str]
    metadata: ReportMetadata


class SynthesisBundle(StrictModel):
    merged_claims: list[str]
    uncovered_aspects: list[str]
    source_weights: dict[str, float]
    sections: list[ReportSection]


class ResearchProgressEvent(StrictModel):
    stage: str
    message: str
    timestamp: datetime
    details: dict[str, Any] = {}


class CreateResearchRunRequest(StrictModel):
    brief: str
    depth: ResearchDepth = ResearchDepth.SHALLOW
    sources: list[ResearchSourceKind] | None = None
    seed_urls: list[str] = []
    prior_research_id: str | None = None
    operator_id: str = "local"
    discord_thread_id: str | None = None


class ApproveResearchPlanRequest(StrictModel):
    approved: bool = True


class ResearchRun(StrictModel):
    id: str
    brief: str
    depth: ResearchDepth
    source_mask: list[ResearchSourceKind]
    status: ResearchRunStatus
    plan: ResearchPlan | None = None
    plan_approved: bool = False
    prior_research: list[PriorResearchRef] = []
    report: ResearchReport | None = None
    artifact_url: str | None = None
    progress: list[ResearchProgressEvent] = []
    errors: list[str] = []
    operator_id: str = "local"
    discord_thread_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
