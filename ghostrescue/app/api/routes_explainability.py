"""Explainability API routes for case analysis transparency."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.schemas import (
    CaseExplainabilityResponse,
    FeedbackHistoryResponse,
)
from app.services.explainability_service import ExplainabilityService
from app.services.trust_service import TrustService

router = APIRouter(prefix="/api/v1", tags=["explainability"])
settings = get_settings()


@router.get("/cases/{case_id}/explainability", response_model=CaseExplainabilityResponse)
async def get_case_explainability(
    case_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get detailed explainability breakdown for a case.

    Returns per-signal contributions, confidence factors, and analyst feedback history.
    Designed for analyst review of system decision-making.
    """
    explainability = await ExplainabilityService(db).case_explainability(case_id)

    if "error" in explainability:
        raise HTTPException(status_code=404, detail=explainability["error"])

    # Enrich with current trust config context
    trust_cfg = await TrustService(db).get_or_create_config()
    explainability["trust_config_context"] = {
        "risk_medium_threshold": trust_cfg.risk_medium_threshold,
        "risk_high_threshold": trust_cfg.risk_high_threshold,
        "risk_critical_threshold": trust_cfg.risk_critical_threshold,
        "false_positive_penalty": trust_cfg.false_positive_penalty,
    }

    return explainability


@router.get("/cases/{case_id}/explainability/html")
async def get_case_explainability_html(
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get HTML visualization page for case explainability.

    Renders signal contributions, confidence breakdown, and feedback summary
    with interactive charts and analyst commentary.
    """
    from fastapi.responses import HTMLResponse

    explainability = await ExplainabilityService(db).case_explainability(case_id)

    if "error" in explainability:
        raise HTTPException(status_code=404, detail=explainability["error"])

    trust_cfg = await TrustService(db).get_or_create_config()

    html_content = _render_explainability_html(explainability, trust_cfg)
    return HTMLResponse(content=html_content)


@router.get("/cases/{case_id}/explainability/feedback", response_model=FeedbackHistoryResponse)
async def get_feedback_history(
    case_id: str,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get analyst feedback history for a case over the past N days."""
    return await ExplainabilityService(db).case_feedback_history(case_id, days=days)


def _render_explainability_html(explainability: dict, trust_cfg) -> str:
    """Render HTML visualization for case explainability."""
    signals = explainability.get("signal_contributions", [])
    feedback = explainability.get("feedback_summary", {})
    conf_breakdown = explainability.get("confidence_breakdown", {})

    # Build signal contributions chart (horizontally stacked bars)
    signal_rows_html = ""
    for sig in signals:
        signal_rows_html += f"""
    <tr>
        <td style="font-weight: bold;">{sig.get('signal_type', 'unknown')}</td>
        <td>{sig.get('label', '')}</td>
        <td style="text-align: center;">{sig.get('confidence', 0):.3f}</td>
        <td>
            <div style="width: 200px; height: 24px; background-color: #f0f0f0; border-radius: 4px; overflow: hidden;">
                <div style="width: {sig.get('weight_pct', 0):.0f}%; height: 100%; background: linear-gradient(90deg, #4CAF50, #8BC34A); display: flex; align-items: center; justify-content: center; color: white; font-size: 12px;">
                    {sig.get('weight_pct', 0):.1f}%
                </div>
            </div>
        </td>
        <td>{sig.get('source_name', 'unknown')[:30]}</td>
    </tr>
        """

    # Confidence breakdown chart (pie-like representation)
    signal_pct = conf_breakdown.get("signal_weight", 0) * 100
    entity_pct = conf_breakdown.get("entity_weight", 0) * 100
    diversity_pct = conf_breakdown.get("diversity_weight", 0) * 100

    # Feedback summary
    feedback_html = f"""
    <div style="background-color: #f9f9f9; padding: 12px; border-radius: 4px; margin: 12px 0;">
        <p><strong>Feedback Count:</strong> {feedback.get('feedback_count', 0)}</p>
        <p><strong>False Positive Rate:</strong> {feedback.get('false_positive_rate', 0) * 100:.1f}% ({feedback.get('false_positive_count', 0)} FP)</p>
        <p><strong>Avg Corrected Risk Score:</strong> {feedback.get('avg_corrected_risk_score', 'N/A')}</p>
    </div>
    """

    # Recent feedbacks
    recent_feedback_html = ""
    for fb in feedback.get("recent_feedback", [])[:5]:
        fb_type = "❌ FALSE POSITIVE" if fb.get("is_false_positive") else "✓ CONFIRMED"
        recent_feedback_html += f"""
    <tr>
        <td>{fb.get('analyst_id', 'unknown')[:20]}</td>
        <td>{fb_type}</td>
        <td>{fb.get('corrected_risk_score', 'N/A')}</td>
        <td>{fb.get('notes', '')[:150]}</td>
        <td style="font-size: 0.85em; color: #999;">{fb.get('created_at', '')[:10]}</td>
    </tr>
        """

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Case Explainability - {explainability.get('case_id', 'Unknown')}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 24px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1, h2, h3 {{
            margin-top: 0;
            color: #1a1a1a;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .case-meta {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .meta-box {{
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 16px;
            border-radius: 6px;
            border-left: 4px solid #2196F3;
        }}
        .meta-label {{
            font-size: 0.85em;
            color: #666;
            margin-bottom: 4px;
        }}
        .meta-value {{
            font-size: 1.4em;
            font-weight: bold;
            color: #1a1a1a;
        }}
        .status-open {{ color: #FF9800; }}
        .status-escalated {{ color: #F44336; }}
        .status-closed {{ color: #4CAF50; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
        }}
        th {{
            background-color: #2196F3;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
        }}
        tr:hover {{
            background-color: #f0f0f0;
        }}
        .disclaimer {{
            background: #FFF3CD;
            border: 1px solid #FFC107;
            border-radius: 4px;
            padding: 12px;
            margin: 16px 0;
            font-size: 0.9em;
            color: #856404;
        }}
        .section {{
            margin-bottom: 32px;
        }}
        .confidence-chart {{
            display: flex;
            gap: 4px;
            height: 30px;
            margin: 16px 0;
            border-radius: 4px;
            overflow: hidden;
        }}
        .conf-segment {{
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 12px;
            font-weight: bold;
        }}
        .signal {{
            background: linear-gradient(135deg, #4CAF50, #8BC34A);
        }}
        .entity {{
            background: linear-gradient(135deg, #2196F3, #64B5F6);
        }}
        .diversity {{
            background: linear-gradient(135deg, #FF9800, #FFB74D);
        }}
        .footer {{
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #e0e0e0;
            font-size: 0.85em;
            color: #999;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Case Explainability Report</h1>
                <p style="color: #999; margin: 4px 0;">Case ID: <code>{explainability.get('case_id', 'N/A')}</code></p>
            </div>
            <div style="text-align: right;">
                <p style="margin: 0; color: #999; font-size: 0.9em;">Generated: {explainability.get('updated_at', 'N/A')[:10]}</p>
            </div>
        </div>

        <div class="disclaimer">
            ⚠️ <strong>Disclaimer:</strong> {explainability.get('disclaimer', 'Outputs are intelligence leads, not verified conclusions.')}
        </div>

        <div class="case-meta">
            <div class="meta-box">
                <div class="meta-label">Status</div>
                <div class="meta-value status-{explainability.get('case_status', 'open')}">{explainability.get('case_status', 'unknown').upper()}</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">Risk Score</div>
                <div class="meta-value">{explainability.get('risk_score', 0):.1f}</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">System Confidence</div>
                <div class="meta-value">{explainability.get('system_confidence', 0):.3f}</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">Signals Detected</div>
                <div class="meta-value">{explainability.get('signal_count', 0)}</div>
            </div>
        </div>

        <!-- SIGNAL CONTRIBUTIONS -->
        <div class="section">
            <h2>📊 Signal Contributions</h2>
            <p style="color: #666; margin-bottom: 12px;">Breakdown of detected signals and their confidence weights in the risk assessment.</p>
            <table>
                <thead>
                    <tr>
                        <th>Signal Type</th>
                        <th>Label</th>
                        <th>Confidence</th>
                        <th>Weight (%)</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody>
                    {signal_rows_html if signal_rows_html else '<tr><td colspan="5" style="text-align: center; color: #999;">No signals detected</td></tr>'}
                </tbody>
            </table>
        </div>

        <!-- CONFIDENCE BREAKDOWN -->
        <div class="section">
            <h2>🎯 Confidence Composition</h2>
            <p style="color: #666; margin-bottom: 12px;">System confidence is computed from signal strength, entity context, and diversity bonus.</p>
            <div>
                <p><strong>Final System Confidence:</strong> <span style="font-size: 1.3em; font-weight: bold; color: #2196F3;">{conf_breakdown.get('final_system_confidence', 0):.3f}</span></p>
            </div>
            <div class="confidence-chart">
                <div class="conf-segment signal" style="flex: {signal_pct};">{signal_pct:.0f}% Signal</div>
                <div class="conf-segment entity" style="flex: {entity_pct};">{entity_pct:.0f}% Entity</div>
                <div class="conf-segment diversity" style="flex: {diversity_pct};">{diversity_pct:.0f}% Diversity</div>
            </div>
            <table style="margin-top: 16px;">
                <thead>
                    <tr>
                        <th>Factor</th>
                        <th>Value</th>
                        <th>Weight</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Signal Confidence Avg</strong></td>
                        <td>{conf_breakdown.get('signal_avg', 0):.3f}</td>
                        <td>{conf_breakdown.get('signal_weight', 0) * 100:.0f}%</td>
                    </tr>
                    <tr>
                        <td><strong>Entity Confidence</strong></td>
                        <td>{conf_breakdown.get('entity_confidence', 0):.3f}</td>
                        <td>{conf_breakdown.get('entity_weight', 0) * 100:.0f}%</td>
                    </tr>
                    <tr>
                        <td><strong>Diversity Bonus</strong></td>
                        <td>{conf_breakdown.get('diversity_bonus', 0):.3f}</td>
                        <td>{conf_breakdown.get('diversity_weight', 0) * 100:.0f}%</td>
                    </tr>
                    <tr style="background-color: #f0f0f0; font-weight: bold;">
                        <td><strong>Calibration Penalty</strong></td>
                        <td>-{conf_breakdown.get('calibration_penalty', 0):.3f}</td>
                        <td>Adaptive</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- FEEDBACK SUMMARY -->
        <div class="section">
            <h2>💬 Analyst Feedback Summary</h2>
            {feedback_html}
            
            <h3>Recent Feedback History</h3>
            <table>
                <thead>
                    <tr>
                        <th>Analyst</th>
                        <th>Type</th>
                        <th>Corrected Risk</th>
                        <th>Notes</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    {recent_feedback_html if recent_feedback_html else '<tr><td colspan="5" style="text-align: center; color: #999;">No feedback yet</td></tr>'}
                </tbody>
            </table>
        </div>

        <!-- TRUST CONFIG -->
        <div class="section">
            <h2>⚙️ Trust Configuration</h2>
            <p style="color: #666; margin-bottom: 12px;">Current system thresholds and penalty settings used for this case.</p>
            <table>
                <thead>
                    <tr>
                        <th>Setting</th>
                        <th>Value</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Medium Risk Threshold</strong></td>
                        <td>{trust_cfg.risk_medium_threshold:.1f}</td>
                    </tr>
                    <tr>
                        <td><strong>High Risk Threshold</strong></td>
                        <td>{trust_cfg.risk_high_threshold:.1f}</td>
                    </tr>
                    <tr>
                        <td><strong>Critical Risk Threshold</strong></td>
                        <td>{trust_cfg.risk_critical_threshold:.1f}</td>
                    </tr>
                    <tr>
                        <td><strong>False Positive Penalty</strong></td>
                        <td>{trust_cfg.false_positive_penalty:.3f}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>Explainability report for analyst review only. All findings require human verification before action.</p>
        </div>
    </div>
</body>
</html>
    """

    return html
