"""Evaluations resource clients — sync and async."""
from __future__ import annotations

from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._types import (
    ABTestRecord,
    ABTestResults,
    AnomalyRecord,
    EvaluationRecord,
    EvaluationSummary,
)


class EvaluationsClient:
    """Synchronous evaluation, anomaly, and A/B test operations."""

    def __init__(self, http: SyncTransport) -> None:
        self._http = http

    def submit(
        self,
        agent_id: str,
        action_id: str,
        *,
        rating_thumbs: str | None = None,
        rating_score: float | None = None,
        notes: str | None = None,
        prompt_version_id: str | None = None,
    ) -> EvaluationRecord:
        """Submit a human evaluation for an action."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/actions/{action_id}/evaluate",
            json={
                "rating_thumbs": rating_thumbs,
                "rating_score": rating_score,
                "notes": notes,
                "prompt_version_id": prompt_version_id,
            },
        )
        return EvaluationRecord._from(data)

    def summary(self, agent_id: str) -> EvaluationSummary:
        """Return aggregated evaluation metrics for an agent."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/evaluations/summary")
        return EvaluationSummary._from(data)

    def list(
        self,
        agent_id: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        prompt_version_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvaluationRecord]:
        """List evaluations for an agent with optional filters."""
        params: dict = {"limit": limit, "offset": offset}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        if prompt_version_id:
            params["prompt_version_id"] = prompt_version_id
        data = self._http.request("GET", f"/v1/agents/{agent_id}/evaluations", params=params)
        return [EvaluationRecord._from(e) for e in data["items"]]

    def list_anomalies(
        self, agent_id: str, *, resolved: bool | None = None
    ) -> list[AnomalyRecord]:
        """List anomalies for an agent."""
        params: dict = {}
        if resolved is not None:
            params["resolved"] = str(resolved).lower()
        data = self._http.request("GET", f"/v1/agents/{agent_id}/anomalies", params=params)
        return [AnomalyRecord._from(a) for a in data["items"]]

    def resolve_anomaly(self, agent_id: str, anomaly_id: str) -> AnomalyRecord:
        """Mark an anomaly as resolved."""
        data = self._http.request(
            "POST", f"/v1/agents/{agent_id}/anomalies/{anomaly_id}/resolve"
        )
        return AnomalyRecord._from(data)

    def create_ab_test(
        self,
        agent_id: str,
        name: str,
        variant_a_prompt_version_id: str,
        variant_b_prompt_version_id: str,
        *,
        traffic_split: float = 0.5,
    ) -> ABTestRecord:
        """Create an A/B test between two prompt versions."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/ab-tests",
            json={
                "name": name,
                "variant_a_prompt_version_id": variant_a_prompt_version_id,
                "variant_b_prompt_version_id": variant_b_prompt_version_id,
                "traffic_split": traffic_split,
            },
        )
        return ABTestRecord._from(data)

    def list_ab_tests(self, agent_id: str) -> list[ABTestRecord]:
        """List all A/B tests for an agent."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/ab-tests")
        return [ABTestRecord._from(t) for t in data["items"]]

    def get_ab_results(self, agent_id: str, test_id: str) -> ABTestResults:
        """Return comparative metrics for each variant in an A/B test."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/ab-tests/{test_id}/results")
        return ABTestResults._from(data)

    def complete_ab_test(
        self, agent_id: str, test_id: str, winner: str
    ) -> ABTestRecord:
        """Close an A/B test, optionally declaring a winner."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/ab-tests/{test_id}/complete",
            json={"winner": winner},
        )
        return ABTestRecord._from(data)


class AsyncEvaluationsClient:
    """Asynchronous evaluation, anomaly, and A/B test operations."""

    def __init__(self, http: AsyncTransport) -> None:
        self._http = http

    async def submit(
        self,
        agent_id: str,
        action_id: str,
        *,
        rating_thumbs: str | None = None,
        rating_score: float | None = None,
        notes: str | None = None,
        prompt_version_id: str | None = None,
    ) -> EvaluationRecord:
        """Submit a human evaluation for an action."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/actions/{action_id}/evaluate",
            json={
                "rating_thumbs": rating_thumbs,
                "rating_score": rating_score,
                "notes": notes,
                "prompt_version_id": prompt_version_id,
            },
        )
        return EvaluationRecord._from(data)

    async def summary(self, agent_id: str) -> EvaluationSummary:
        """Return aggregated evaluation metrics for an agent."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/evaluations/summary")
        return EvaluationSummary._from(data)

    async def list(
        self,
        agent_id: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        prompt_version_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvaluationRecord]:
        """List evaluations for an agent with optional filters."""
        params: dict = {"limit": limit, "offset": offset}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        if prompt_version_id:
            params["prompt_version_id"] = prompt_version_id
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/evaluations", params=params)
        return [EvaluationRecord._from(e) for e in data["items"]]

    async def list_anomalies(
        self, agent_id: str, *, resolved: bool | None = None
    ) -> list[AnomalyRecord]:
        """List anomalies for an agent."""
        params: dict = {}
        if resolved is not None:
            params["resolved"] = str(resolved).lower()
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/anomalies", params=params)
        return [AnomalyRecord._from(a) for a in data["items"]]

    async def resolve_anomaly(self, agent_id: str, anomaly_id: str) -> AnomalyRecord:
        """Mark an anomaly as resolved."""
        data = await self._http.request(
            "POST", f"/v1/agents/{agent_id}/anomalies/{anomaly_id}/resolve"
        )
        return AnomalyRecord._from(data)

    async def create_ab_test(
        self,
        agent_id: str,
        name: str,
        variant_a_prompt_version_id: str,
        variant_b_prompt_version_id: str,
        *,
        traffic_split: float = 0.5,
    ) -> ABTestRecord:
        """Create an A/B test between two prompt versions."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/ab-tests",
            json={
                "name": name,
                "variant_a_prompt_version_id": variant_a_prompt_version_id,
                "variant_b_prompt_version_id": variant_b_prompt_version_id,
                "traffic_split": traffic_split,
            },
        )
        return ABTestRecord._from(data)

    async def list_ab_tests(self, agent_id: str) -> list[ABTestRecord]:
        """List all A/B tests for an agent."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/ab-tests")
        return [ABTestRecord._from(t) for t in data["items"]]

    async def get_ab_results(self, agent_id: str, test_id: str) -> ABTestResults:
        """Return comparative metrics for each variant in an A/B test."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/ab-tests/{test_id}/results")
        return ABTestResults._from(data)

    async def complete_ab_test(
        self, agent_id: str, test_id: str, winner: str
    ) -> ABTestRecord:
        """Close an A/B test, optionally declaring a winner."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/ab-tests/{test_id}/complete",
            json={"winner": winner},
        )
        return ABTestRecord._from(data)
