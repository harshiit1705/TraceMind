"""Unit and algorithmic integration tests for the deterministic cross-service correlation engine and ranker."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from sqlalchemy.orm import Session

from app.models.anomaly import AnomalyEvent
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.schemas.correlation import CorrelationConfig, RankingConfidence
from app.services.correlation.engine import CorrelationEngine
from app.services.correlation.ranker import RootCauseRanker


def create_anomaly(
    db_session: Session,
    project_id: UUID,
    service_id: UUID,
    metric_name: str,
    observed_value: float,
    baseline: float,
    deviation_pct: float,
    occurred_at: datetime,
    severity: str = "high",
) -> AnomalyEvent:
    ev = AnomalyEvent(
        id=uuid4(),
        project_id=project_id,
        service_id=service_id,
        metric_name=metric_name,
        observed_value=observed_value,
        expected_baseline=baseline,
        deviation_pct=deviation_pct,
        severity=severity,
        detection_method="rolling_average",
        occurred_at=occurred_at,
        status="open",
        explanation=f"Test anomaly on {metric_name}",
    )
    db_session.add(ev)
    db_session.commit()
    db_session.refresh(ev)
    return ev


def test_two_temporally_related_anomalies_in_dependent_services(db_session: Session):
    """Scenario: Inventory Service anomalies at 10:02, Order Service at 10:03.
    Order Service depends on Inventory Service.
    Engine must group them, and Inventory Service must rank #1 as probable root cause.
    """
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    assert proj is not None

    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()
    assert inv_svc is not None and order_svc is not None

    t0 = datetime(2026, 11, 6, 10, 2, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 10, 3, 0, tzinfo=timezone.utc)

    # 1. Create anomaly on Inventory Service (upstream) at 10:02
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 450.0, 45.0, 900.0, t0, severity="critical")

    # 2. Create anomaly on Order Service (downstream) at 10:03
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 1800.0, 180.0, 900.0, t1, severity="critical")

    # Evaluate
    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.events_count == 2
    assert group.topology_complete is True
    assert len(group.ranked_candidates) == 2

    # Inventory Service must be ranked #1
    top_candidate = group.ranked_candidates[0]
    second_candidate = group.ranked_candidates[1]

    assert top_candidate.service_id == inv_svc.id
    assert top_candidate.rank == 1
    assert top_candidate.is_probable_root_cause is True
    assert top_candidate.confidence == RankingConfidence.HIGH
    assert top_candidate.score > second_candidate.score

    # Check breakdown explainability
    breakdown = top_candidate.breakdown
    assert breakdown.temporal_precedence.score == 1.0  # Occurred first
    assert breakdown.topological_position.score == 1.0  # Pure upstream in this group
    assert breakdown.blast_radius.score == 1.0          # Explains 1 of 1 affected downstream services

    # Order Service (downstream)
    assert second_candidate.service_id == order_svc.id
    assert second_candidate.rank == 2
    assert second_candidate.is_probable_root_cause is False
    assert second_candidate.breakdown.topological_position.score == 0.10  # Penalized as downstream caller


def test_two_anomalies_in_unrelated_services(db_session: Session):
    """Anomalies in topologically disconnected services should not be falsely clustered into a cascade."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    recs_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="recommendation-engine").first()
    search_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="search-indexer").first()
    assert recs_svc is not None and search_svc is not None

    t0 = datetime(2026, 11, 6, 11, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 11, 1, 0, tzinfo=timezone.utc)

    # Both have anomalies close in time, but no dependency link connects them
    create_anomaly(db_session, proj.id, recs_svc.id, "latency", 500.0, 100.0, 400.0, t0)
    create_anomaly(db_session, proj.id, search_svc.id, "latency", 600.0, 100.0, 500.0, t1)

    engine = CorrelationEngine(db_session)
    config = CorrelationConfig(min_events_per_group=2)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
        config=config,
    )

    # Since they are in disjoint components of size 1, neither meets min_events_per_group=2
    assert len(groups) == 0


def test_downstream_anomaly_preceding_upstream_anomaly(db_session: Session):
    """When a downstream anomaly precedes the upstream anomaly, ranker must account for topological vs temporal divergence."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t_downstream = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
    t_upstream = datetime(2026, 11, 6, 12, 2, 0, tzinfo=timezone.utc)

    # Downstream Order Service anomalous at 12:00
    create_anomaly(db_session, proj.id, order_svc.id, "error_rate", 12.0, 1.0, 1100.0, t_downstream)
    # Upstream Inventory Service anomalous at 12:02
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 300.0, 40.0, 650.0, t_upstream)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_downstream - timedelta(minutes=1),
        end_time=t_upstream + timedelta(minutes=1),
    )

    assert len(groups) == 1
    candidates = groups[0].ranked_candidates
    assert len(candidates) == 2

    # Verify breakdown:
    # Order Service had earlier temporal score (1.0), but lower topological score (0.10)
    order_cand = next(c for c in candidates if c.service_id == order_svc.id)
    inv_cand = next(c for c in candidates if c.service_id == inv_svc.id)

    assert order_cand.breakdown.temporal_precedence.score == 1.0
    assert order_cand.breakdown.topological_position.score == 0.10

    assert inv_cand.breakdown.temporal_precedence.score == 0.0
    assert inv_cand.breakdown.topological_position.score == 1.0


def test_missing_dependency_information_handled_safely(db_session: Session):
    """When no dependency edges exist for participating services, confidence is lowered and topology_complete is False."""
    # Create isolated project without dependencies
    org = db_session.query(Organization).first()
    proj = Project(
        organization_id=org.id,
        slug="unmapped-project",
        name="Unmapped Topology Project",
        environment="test",
    )
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    s1 = Service(project_id=proj.id, slug="srv-alpha", name="Server Alpha", identifier="svc:srv-alpha")
    s2 = Service(project_id=proj.id, slug="srv-beta", name="Server Beta", identifier="svc:srv-beta")
    db_session.add_all([s1, s2])
    db_session.commit()

    t0 = datetime(2026, 11, 6, 13, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 13, 1, 0, tzinfo=timezone.utc)

    create_anomaly(db_session, proj.id, s1.id, "cpu", 95.0, 50.0, 90.0, t0)
    create_anomaly(db_session, proj.id, s2.id, "cpu", 99.0, 50.0, 98.0, t1)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.topology_complete is False  # Explicit flag
    assert group.ranked_candidates[0].confidence == RankingConfidence.LOW
    assert "insufficient topology evidence" in group.ranked_candidates[0].breakdown.topological_position.reason.lower()


def test_deterministic_tie_breaking(db_session: Session):
    """When two candidates have identical scores, sorting must be strictly deterministic by timestamp and identifier."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    s1 = db_session.query(Service).filter_by(project_id=proj.id, slug="user-service").first()
    s2 = db_session.query(Service).filter_by(project_id=proj.id, slug="auth-service").first()

    # Identical timestamp, identical metrics, identical severity
    same_time = datetime(2026, 11, 6, 14, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, s1.id, "latency", 100.0, 10.0, 900.0, same_time, severity="high")
    create_anomaly(db_session, proj.id, s2.id, "latency", 100.0, 10.0, 900.0, same_time, severity="high")

    # Call ranker directly with no mutual edges
    ranked = RootCauseRanker.rank_candidates(
        participating_services={s1.id: s1, s2.id: s2},
        events_by_service={
            s1.id: [db_session.query(AnomalyEvent).filter_by(service_id=s1.id).first()],
            s2.id: [db_session.query(AnomalyEvent).filter_by(service_id=s2.id).first()],
        },
        upstream_map={s1.id: set(), s2.id: set()},
        downstream_map={s1.id: set(), s2.id: set()},
        topology_edges_exist=False,
    )

    assert len(ranked) == 2
    # Verify exact tie-breaker ordering: s2 (auth-service: "svc:oauth-jwt-issuer") before s1 (user-service: "svc:accounts-core")
    # or sorted alphabetically by identifier
    expected_order = sorted([s1, s2], key=lambda s: s.identifier)
    assert ranked[0].service_id == expected_order[0].id
    assert ranked[1].service_id == expected_order[1].id


def test_project_isolation_prevents_cross_project_correlation(db_session: Session):
    """Anomalies from different projects are never correlated together."""
    proj1 = db_session.query(Project).filter_by(slug="core-ecommerce").first()

    org = db_session.query(Organization).first()
    proj2 = Project(
        organization_id=org.id,
        slug="isolated-analytics",
        name="Isolated Analytics",
        environment="production",
    )
    db_session.add(proj2)
    db_session.commit()
    db_session.refresh(proj2)

    svc_p2 = Service(project_id=proj2.id, slug="analytics-collector", name="Analytics Collector", identifier="svc:analytics-collector")
    db_session.add(svc_p2)
    db_session.commit()
    db_session.refresh(svc_p2)

    svc_p1 = db_session.query(Service).filter_by(project_id=proj1.id, slug="api-gateway").first()

    t = datetime(2026, 11, 6, 15, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj1.id, svc_p1.id, "latency", 500.0, 100.0, 400.0, t)
    create_anomaly(db_session, proj2.id, svc_p2.id, "latency", 500.0, 100.0, 400.0, t)

    engine = CorrelationEngine(db_session)
    # Evaluate Project 1 only
    p1_groups = engine.evaluate(
        project_id=proj1.id,
        start_time=t - timedelta(minutes=1),
        end_time=t + timedelta(minutes=1),
    )
    for g in p1_groups:
        for ev in g.participating_events:
            assert ev.service_id != svc_p2.id


def test_connected_services_hours_apart_separated_by_max_cascade_delay(db_session: Session):
    """Connected services with anomalies hours apart must not be falsely grouped into a single cascade."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t_morning = datetime(2026, 11, 6, 8, 0, 0, tzinfo=timezone.utc)
    t_afternoon = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)

    # 4 hours apart
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 500.0, 50.0, 900.0, t_morning)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 800.0, 80.0, 900.0, t_afternoon)

    engine = CorrelationEngine(db_session)
    # Default min_events_per_group=2: separate clusters of size 1 do not form groups
    groups_def = engine.evaluate(
        project_id=proj.id,
        start_time=t_morning - timedelta(minutes=5),
        end_time=t_afternoon + timedelta(minutes=5),
        config=CorrelationConfig(min_events_per_group=2, max_cascade_delay_seconds=300),
    )
    assert len(groups_def) == 0

    # With min_events_per_group=1, they form 2 separate isolated groups
    groups_single = engine.evaluate(
        project_id=proj.id,
        start_time=t_morning - timedelta(minutes=5),
        end_time=t_afternoon + timedelta(minutes=5),
        config=CorrelationConfig(min_events_per_group=1, max_cascade_delay_seconds=300),
    )
    assert len(groups_single) == 2
    assert {g.events_count for g in groups_single} == {1}


def test_multiple_anomalies_on_same_service_within_window(db_session: Session):
    """Multiple metric anomalies on the same service within window form a coherent incident group."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t0 = datetime(2026, 11, 6, 16, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 16, 0, 30, tzinfo=timezone.utc)

    # Anomaly 1: latency spike
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 2500.0, 200.0, 1150.0, t0, severity="high")
    # Anomaly 2: error rate surge
    create_anomaly(db_session, proj.id, order_svc.id, "error_rate", 18.0, 0.5, 3500.0, t1, severity="critical")

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
        config=CorrelationConfig(min_events_per_group=2),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.events_count == 2
    assert len(group.ranked_candidates) == 1

    cand = group.ranked_candidates[0]
    assert cand.service_id == order_svc.id
    assert cand.is_probable_root_cause is True
    assert cand.breakdown.topological_position.score == 1.0  # Sole affected service
    assert cand.breakdown.blast_radius.score == 0.0          # No other services affected
    assert cand.confidence == RankingConfidence.MEDIUM


def test_exact_start_and_end_window_boundaries_included(db_session: Session):
    """Events occurring at exact start_time and end_time boundaries must be included."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t_start = datetime(2026, 11, 6, 18, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 11, 6, 18, 2, 0, tzinfo=timezone.utc)

    # Exact boundary events
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 400.0, 40.0, 900.0, t_start)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 700.0, 70.0, 900.0, t_end)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_start,
        end_time=t_end,
    )

    assert len(groups) == 1
    assert groups[0].events_count == 2
    # Normalize tzinfo for SQLite compatibility where SQLite stores naive datetimes
    event_times = {
        ev.occurred_at.replace(tzinfo=timezone.utc) if ev.occurred_at.tzinfo is None else ev.occurred_at
        for ev in groups[0].participating_events
    }
    assert t_start in event_times
    assert t_end in event_times


def test_upstream_candidate_lower_severity_still_ranks_first(db_session: Session):
    """An upstream service with lower severity still ranks higher than downstream with critical severity."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t0 = datetime(2026, 11, 6, 19, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 19, 0, 30, tzinfo=timezone.utc)

    # Upstream has low severity (+30% deviation)
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 52.0, 40.0, 30.0, t0, severity="low")
    # Downstream has critical severity (+2000% deviation)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 2100.0, 100.0, 2000.0, t1, severity="critical")

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
    )

    assert len(groups) == 1
    candidates = groups[0].ranked_candidates
    assert len(candidates) == 2
    # Inventory Service (upstream) still wins
    assert candidates[0].service_id == inv_svc.id
    assert candidates[0].rank == 1
    assert candidates[0].is_probable_root_cause is True
    assert candidates[0].score > candidates[1].score


def test_multiple_upstream_candidates_broken_by_earlier_timestamp(db_session: Session):
    """When multiple services are upstream of a downstream service, the earlier upstream anomaly ranks higher."""
    # Build isolated project with 2 upstream services (U1, U2) calling Downstream (D)
    org = db_session.query(Organization).first()
    proj = Project(organization_id=org.id, slug="multi-upstream-test", name="Multi Upstream", environment="test")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    u1 = Service(project_id=proj.id, slug="upstream-1", name="Upstream 1", identifier="svc:upstream-1")
    u2 = Service(project_id=proj.id, slug="upstream-2", name="Upstream 2", identifier="svc:upstream-2")
    d = Service(project_id=proj.id, slug="downstream", name="Downstream", identifier="svc:downstream")
    db_session.add_all([u1, u2, d])
    db_session.commit()

    # D depends on U1 and U2 (D -> U1, D -> U2)
    dep1 = ServiceDependency(project_id=proj.id, source_service_id=d.id, target_service_id=u1.id, dependency_type="synchronous")
    dep2 = ServiceDependency(project_id=proj.id, source_service_id=d.id, target_service_id=u2.id, dependency_type="synchronous")
    db_session.add_all([dep1, dep2])
    db_session.commit()

    t0 = datetime(2026, 11, 6, 20, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 6, 20, 0, 10, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 6, 20, 0, 20, tzinfo=timezone.utc)

    create_anomaly(db_session, proj.id, u1.id, "latency", 500.0, 50.0, 900.0, t0, severity="high")
    create_anomaly(db_session, proj.id, u2.id, "latency", 500.0, 50.0, 900.0, t1, severity="high")
    create_anomaly(db_session, proj.id, d.id, "latency", 800.0, 80.0, 900.0, t2, severity="high")

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t2 + timedelta(minutes=1),
    )

    assert len(groups) == 1
    cands = groups[0].ranked_candidates
    assert len(cands) == 3
    # U1 was earlier than U2, so U1 must rank #1
    assert cands[0].service_id == u1.id
    assert cands[1].service_id == u2.id
    assert cands[2].service_id == d.id
    assert cands[0].score > cands[1].score > cands[2].score


def test_reproduce_three_event_temporal_chaining_prevented(db_session: Session):
    """Event A (10:00), Event B (10:04), Event C (10:08) where consecutive delays are 4m (<= 5m),
    but total timespan is 8m (> 5m). With max_incident_duration_seconds=300, chaining is prevented.
    """
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()
    pay_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="payment-service").first()

    t0 = datetime(2026, 11, 6, 21, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=4)  # +240s
    t2 = t0 + timedelta(minutes=8)  # +480s

    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 500.0, 50.0, 900.0, t0)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 800.0, 80.0, 900.0, t1)
    create_anomaly(db_session, proj.id, pay_svc.id, "latency", 900.0, 90.0, 900.0, t2)

    engine = CorrelationEngine(db_session)

    # 1. Default max_incident_duration_seconds (defaults to max_cascade_delay_seconds = 300s):
    # Total span between t0 and t2 is 480s > 300s. Event C must NOT chain into Group 1!
    groups_bounded = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t2 + timedelta(minutes=2),
        config=CorrelationConfig(max_cascade_delay_seconds=300, min_events_per_group=1),
    )
    assert len(groups_bounded) == 2
    g1 = groups_bounded[0]
    g2 = groups_bounded[1]

    # Group 1 has Inventory and Order services (duration 240s <= 300s)
    assert g1.events_count == 2
    g1_svc_ids = {e.service_id for e in g1.participating_events}
    assert g1_svc_ids == {inv_svc.id, order_svc.id}
    assert (g1.time_window_end - g1.time_window_start).total_seconds() == 240.0

    # Group 2 has Payment service (duration 0s <= 300s)
    assert g2.events_count == 1
    assert g2.participating_events[0].service_id == pay_svc.id

    # 2. When explicitly configured with a larger max_incident_duration_seconds (e.g. 600s = 10 min),
    # legitimate slow cascading failures are permitted across the 8-minute span:
    groups_extended = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t2 + timedelta(minutes=2),
        config=CorrelationConfig(
            max_cascade_delay_seconds=300,
            max_incident_duration_seconds=600,
            min_events_per_group=1,
        ),
    )
    assert len(groups_extended) == 1
    assert groups_extended[0].events_count == 3
    assert (groups_extended[0].time_window_end - groups_extended[0].time_window_start).total_seconds() == 480.0


def test_long_chain_multi_service_bounded(db_session: Session):
    """5 dependent services failing at 4-minute intervals (total 16 minutes) must not form a single runaway incident."""
    org = db_session.query(Organization).first()
    proj = Project(organization_id=org.id, slug="long-chain-test", name="Long Chain Test", environment="test")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    services = []
    for i in range(1, 6):
        svc = Service(project_id=proj.id, slug=f"svc-node-{i}", name=f"Node {i}", identifier=f"svc:node-{i}")
        db_session.add(svc)
        services.append(svc)
    db_session.commit()

    # Chain: S2->S1, S3->S2, S4->S3, S5->S4
    for i in range(4):
        dep = ServiceDependency(project_id=proj.id, source_service_id=services[i+1].id, target_service_id=services[i].id, dependency_type="sync")
        db_session.add(dep)
    db_session.commit()

    t_start = datetime(2026, 11, 6, 22, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        t_ev = t_start + timedelta(minutes=4 * i)  # 0m, 4m, 8m, 12m, 16m
        create_anomaly(db_session, proj.id, services[i].id, "latency", 500.0, 50.0, 900.0, t_ev)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_start - timedelta(minutes=1),
        end_time=t_start + timedelta(minutes=20),
        config=CorrelationConfig(max_cascade_delay_seconds=300, max_incident_duration_seconds=300, min_events_per_group=1),
    )

    # Must be partitioned into bounded groups, not a single 16-minute runaway cluster
    assert len(groups) > 1
    for g in groups:
        span_s = (g.time_window_end - g.time_window_start).total_seconds()
        assert span_s <= 300.0


def test_legitimate_cascading_failure_across_multiple_services(db_session: Session):
    """Legitimate cascading failure where 4 services degrade within 2 minutes must be grouped into 1 incident."""
    org = db_session.query(Organization).first()
    proj = Project(organization_id=org.id, slug="legit-cascade-test", name="Legit Cascade", environment="test")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    s1 = Service(project_id=proj.id, slug="db-core", name="DB Core", identifier="svc:db-core")
    s2 = Service(project_id=proj.id, slug="user-api", name="User API", identifier="svc:user-api")
    s3 = Service(project_id=proj.id, slug="order-api", name="Order API", identifier="svc:order-api")
    s4 = Service(project_id=proj.id, slug="gateway", name="Gateway", identifier="svc:gateway")
    db_session.add_all([s1, s2, s3, s4])
    db_session.commit()

    # Gateway -> Order -> User -> DB
    db_session.add_all([
        ServiceDependency(project_id=proj.id, source_service_id=s4.id, target_service_id=s3.id, dependency_type="sync"),
        ServiceDependency(project_id=proj.id, source_service_id=s3.id, target_service_id=s2.id, dependency_type="sync"),
        ServiceDependency(project_id=proj.id, source_service_id=s2.id, target_service_id=s1.id, dependency_type="sync"),
    ])
    db_session.commit()

    t0 = datetime(2026, 11, 6, 23, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, s1.id, "connection_count", 950.0, 100.0, 850.0, t0, severity="critical")
    create_anomaly(db_session, proj.id, s2.id, "latency", 1500.0, 50.0, 2900.0, t0 + timedelta(seconds=30), severity="high")
    create_anomaly(db_session, proj.id, s3.id, "latency", 2500.0, 100.0, 2400.0, t0 + timedelta(seconds=60), severity="high")
    create_anomaly(db_session, proj.id, s4.id, "error_rate", 25.0, 0.1, 24900.0, t0 + timedelta(seconds=90), severity="critical")

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t0 + timedelta(minutes=3),
    )

    assert len(groups) == 1
    g = groups[0]
    assert g.events_count == 4
    assert len(g.ranked_candidates) == 4
    # Root cause candidate must be DB Core (s1)
    assert g.ranked_candidates[0].service_id == s1.id
    assert g.ranked_candidates[0].is_probable_root_cause is True
    assert g.ranked_candidates[0].confidence == RankingConfidence.HIGH


def test_events_outside_pairwise_delay_separated(db_session: Session):
    """Anomalies separated by more than max_cascade_delay_seconds must be separated into distinct groups."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t0 = datetime(2026, 11, 7, 0, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=360)  # 6 minutes apart (> 300s max delay)

    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 500.0, 50.0, 900.0, t0)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 800.0, 80.0, 900.0, t1)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t1 + timedelta(minutes=1),
        config=CorrelationConfig(max_cascade_delay_seconds=300, min_events_per_group=1),
    )
    assert len(groups) == 2
    assert {g.events_count for g in groups} == {1}


def test_multiple_anomalies_same_service_grouped(db_session: Session):
    """Multiple distinct metric anomalies on the same service within window form a single group."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t = datetime(2026, 11, 7, 1, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 1200.0, 100.0, 1100.0, t, severity="high")
    create_anomaly(db_session, proj.id, order_svc.id, "error_rate", 15.0, 0.5, 2900.0, t + timedelta(seconds=20), severity="critical")
    create_anomaly(db_session, proj.id, order_svc.id, "cpu", 98.0, 40.0, 145.0, t + timedelta(seconds=40), severity="high")

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t - timedelta(minutes=1),
        end_time=t + timedelta(minutes=2),
    )
    assert len(groups) == 1
    assert groups[0].events_count == 3
    assert len(groups[0].ranked_candidates) == 1
    assert groups[0].ranked_candidates[0].service_id == order_svc.id


def test_exact_time_boundary_handling(db_session: Session):
    """Exact max_cascade_delay_seconds boundaries: == max_delay connects, > max_delay separates."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t0 = datetime(2026, 11, 7, 2, 0, 0, tzinfo=timezone.utc)
    t_exact_300 = t0 + timedelta(seconds=300)

    # Exactly 300.0 seconds apart
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 400.0, 40.0, 900.0, t0)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 700.0, 70.0, 900.0, t_exact_300)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t0 - timedelta(minutes=1),
        end_time=t_exact_300 + timedelta(minutes=1),
        config=CorrelationConfig(max_cascade_delay_seconds=300),
    )
    assert len(groups) == 1
    assert groups[0].events_count == 2


def test_utc_and_timezone_consistency(db_session: Session):
    """Timestamps in UTC timezone preserve exact delta calculation without offset anomalies."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    t_utc = datetime(2026, 11, 7, 3, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 400.0, 40.0, 900.0, t_utc)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 600.0, 60.0, 900.0, t_utc + timedelta(seconds=90))

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_utc - timedelta(minutes=1),
        end_time=t_utc + timedelta(minutes=3),
    )
    assert len(groups) == 1
    g = groups[0]
    span = (g.time_window_end - g.time_window_start).total_seconds()
    assert abs(span - 90.0) < 1e-3


def test_disconnected_services_close_in_time(db_session: Session):
    """Services with no dependency relationships occurring at the same timestamp are not grouped together."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    recs_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="recommendation-engine").first()
    search_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="search-indexer").first()

    # Disconnected services both spike at exactly the same second
    t = datetime(2026, 11, 7, 4, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, recs_svc.id, "latency", 600.0, 100.0, 500.0, t)
    create_anomaly(db_session, proj.id, search_svc.id, "latency", 700.0, 100.0, 600.0, t)

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t - timedelta(minutes=1),
        end_time=t + timedelta(minutes=1),
        config=CorrelationConfig(min_events_per_group=2),
    )
    assert len(groups) == 0


def test_multiple_independent_incidents_in_same_window(db_session: Session):
    """Multiple independent incidents occurring in different parts of a large window produce separate groups."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    # Incident 1 at 05:00 UTC
    t_inc1 = datetime(2026, 11, 7, 5, 0, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, inv_svc.id, "latency", 400.0, 40.0, 900.0, t_inc1)
    create_anomaly(db_session, proj.id, order_svc.id, "latency", 700.0, 70.0, 900.0, t_inc1 + timedelta(seconds=45))

    # Incident 2 at 05:40 UTC (40 minutes later)
    t_inc2 = datetime(2026, 11, 7, 5, 40, 0, tzinfo=timezone.utc)
    create_anomaly(db_session, proj.id, inv_svc.id, "error_rate", 20.0, 0.5, 3900.0, t_inc2)
    create_anomaly(db_session, proj.id, order_svc.id, "error_rate", 25.0, 0.5, 4900.0, t_inc2 + timedelta(seconds=30))

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_inc1 - timedelta(minutes=5),
        end_time=t_inc2 + timedelta(minutes=5),
    )

    assert len(groups) == 2
    # Verify both incidents are separate
    assert groups[0].events_count == 2
    assert groups[1].events_count == 2
    assert groups[0].correlation_key != groups[1].correlation_key
    assert groups[0].time_window_start != groups[1].time_window_start


def test_identical_timestamps_secondary_ordering_determinism(db_session: Session):
    """Multiple anomaly events with identical timestamps must order deterministically by AnomalyEvent.id.asc()."""
    proj = db_session.query(Project).filter_by(slug="core-ecommerce").first()
    inv_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="inventory-service").first()
    order_svc = db_session.query(Service).filter_by(project_id=proj.id, slug="order-service").first()

    # Identical microsecond timestamp
    t_exact = datetime(2026, 11, 7, 6, 0, 0, 123456, tzinfo=timezone.utc)

    # Deterministic UUIDs to test ordering
    id_low = UUID("11111111-1111-1111-1111-111111111111")
    id_high = UUID("99999999-9999-9999-9999-999999999999")

    # Insert id_high first, then id_low to ensure DB insertion order does not dictate evaluation order
    ev_high = AnomalyEvent(
        id=id_high,
        project_id=proj.id,
        service_id=order_svc.id,
        metric_name="latency",
        observed_value=800.0,
        expected_baseline=80.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t_exact,
        status="open",
    )
    ev_low = AnomalyEvent(
        id=id_low,
        project_id=proj.id,
        service_id=inv_svc.id,
        metric_name="latency",
        observed_value=500.0,
        expected_baseline=50.0,
        deviation_pct=900.0,
        severity="high",
        detection_method="rolling_average",
        occurred_at=t_exact,
        status="open",
    )
    db_session.add_all([ev_high, ev_low])
    db_session.commit()

    engine = CorrelationEngine(db_session)
    groups = engine.evaluate(
        project_id=proj.id,
        start_time=t_exact - timedelta(minutes=1),
        end_time=t_exact + timedelta(minutes=1),
    )

    assert len(groups) == 1
    g = groups[0]
    assert g.events_count == 2
    # Verify that in participating_events, the event with id_low is ordered first
    assert g.participating_events[0].event_id == id_low
    assert g.participating_events[1].event_id == id_high

