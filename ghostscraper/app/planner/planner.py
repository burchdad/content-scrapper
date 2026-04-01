from app.core.enums import Intent, Strategy
from app.models.plans import ScrapePlan
from app.models.requests import ScrapeRequest
from app.planner.intent_classifier import infer_intent
from app.planner.schema_inference import infer_fields


class Planner:
    def build_plan(self, request: ScrapeRequest) -> ScrapePlan:
        intent = self._infer_intent(request.query)
        fields = self._infer_fields(intent, request.desired_fields, request.custom_schema)
        strategy = self._select_strategy(request, intent)

        needs_images = request.include_images or intent in {Intent.REAL_ESTATE, Intent.PRODUCTS, Intent.MEDIA}
        hints = self._build_hints(intent, request)
        use_playwright = self._should_use_playwright(request, intent)

        return ScrapePlan(
            intent=intent.value,
            strategy=strategy.value,
            fields=fields,
            candidate_queries=[request.query],
            target_urls=[str(w) for w in request.websites] if request.websites else [],
            extraction_hints=hints,
            use_playwright=use_playwright,
            paginate=request.paginate,
            click_galleries=intent in {Intent.REAL_ESTATE, Intent.MEDIA},
            capture_images=needs_images,
        )

    def _infer_intent(self, query: str) -> Intent:
        return infer_intent(query)

    def _infer_fields(self, intent: Intent, desired_fields: list[str] | None, custom_schema: dict | None):
        return infer_fields(intent, desired_fields, custom_schema)

    def _select_strategy(self, request: ScrapeRequest, intent: Intent) -> Strategy:
        if request.mode == "dynamic":
            return Strategy.DIRECT_DYNAMIC if request.websites else Strategy.HYBRID
        if request.mode == "static":
            return Strategy.DIRECT_STATIC if request.websites else Strategy.SEARCH_THEN_SCRAPE

        if request.websites:
            if intent in {Intent.REAL_ESTATE, Intent.PRODUCTS, Intent.MEDIA}:
                return Strategy.HYBRID
            return Strategy.DIRECT_STATIC

        return Strategy.SEARCH_THEN_SCRAPE

    def _build_hints(self, intent: Intent, request: ScrapeRequest) -> list[str]:
        hints = [f"intent:{intent.value}"]
        if request.include_images:
            hints.append("extract:images")
        if request.include_videos:
            hints.append("extract:videos")
        if intent == Intent.REAL_ESTATE:
            hints.extend(["extract:price", "extract:beds_baths_sqft", "prioritize:galleries"])
        if intent == Intent.MEDIA:
            hints.extend(["extract:social_links", "extract:embeds", "prioritize:rich_media"])
        return hints

    def _should_use_playwright(self, request: ScrapeRequest, intent: Intent) -> bool:
        if request.mode == "static":
            return False
        if request.mode == "dynamic":
            return True
        return intent in {Intent.REAL_ESTATE, Intent.PRODUCTS, Intent.MEDIA}
