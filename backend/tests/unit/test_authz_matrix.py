"""Authorization matrix (FR-A5, Appendix D.5).

⚠ The expectation grid below is **hand-written on purpose**. Importing
``ROLE_PERMISSIONS`` and asserting it equals itself would pass forever while
proving nothing. If a permission moves between roles, one of these rows has to
be changed by a human who thought about it.
"""

from __future__ import annotations

import uuid

import pytest

from app.authz.perms import Perm
from app.authz.policy import Principal, authorize_owned, has_perm, require_perm
from app.core.errors import PermissionError_
from app.domain.enums import OrgRole

# role -> the exact capability set it should hold. Written out, not derived.
EXPECTED: dict[OrgRole, set[Perm]] = {
    OrgRole.MEMBER: {
        Perm.RESUME_MANAGE,
        Perm.JD_MANAGE,
        Perm.SESSION_START,
        Perm.SESSION_ANSWER,
        Perm.SESSION_READ_OWN,
        Perm.REPORT_READ_OWN,
    },
    OrgRole.REVIEWER: {
        Perm.RESUME_MANAGE,
        Perm.JD_MANAGE,
        Perm.SESSION_START,
        Perm.SESSION_ANSWER,
        Perm.SESSION_READ_OWN,
        Perm.REPORT_READ_OWN,
        Perm.SESSION_READ_ORG,
        Perm.REVIEW_WRITE,
    },
    OrgRole.ADMIN: {
        Perm.RESUME_MANAGE,
        Perm.JD_MANAGE,
        Perm.SESSION_START,
        Perm.SESSION_ANSWER,
        Perm.SESSION_READ_OWN,
        Perm.REPORT_READ_OWN,
        Perm.SESSION_READ_ORG,
        Perm.REVIEW_WRITE,
        Perm.POSTING_MANAGE,
        Perm.MEMBER_MANAGE,
    },
    OrgRole.OWNER: {
        Perm.RESUME_MANAGE,
        Perm.JD_MANAGE,
        Perm.SESSION_START,
        Perm.SESSION_ANSWER,
        Perm.SESSION_READ_OWN,
        Perm.REPORT_READ_OWN,
        Perm.SESSION_READ_ORG,
        Perm.REVIEW_WRITE,
        Perm.POSTING_MANAGE,
        Perm.MEMBER_MANAGE,
        Perm.ORG_MANAGE,
        Perm.BANK_MANAGE,
    },
}


def _principal(role: OrgRole, org: uuid.UUID | None = None) -> Principal:
    return Principal.build(uuid.uuid4(), org or uuid.uuid4(), role)


@pytest.mark.parametrize("role", sorted(EXPECTED, key=lambda r: r.value))
@pytest.mark.parametrize("perm", sorted(Perm, key=lambda p: p.value))
def test_permission_grid(role: OrgRole, perm: Perm) -> None:
    principal = _principal(role)
    expected = perm in EXPECTED[role]
    assert has_perm(principal, perm) is expected, (
        f"{role.value} should {'have' if expected else 'NOT have'} {perm.value}"
    )


def test_anonymous_has_nothing() -> None:
    for perm in Perm:
        assert has_perm(None, perm) is False
    with pytest.raises(PermissionError_):
        require_perm(None, Perm.SESSION_START)


def test_owner_can_access_own_resource() -> None:
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    principal = Principal.build(user_id, org_id, OrgRole.MEMBER)
    authorize_owned(principal, owner_user_id=user_id, organization_id=org_id)


def test_member_cannot_read_another_users_session() -> None:
    """The bug class this prevents is object-level access control (IDOR)."""
    principal = _principal(OrgRole.MEMBER)
    with pytest.raises(PermissionError_):
        authorize_owned(
            principal,
            owner_user_id=uuid.uuid4(),
            organization_id=principal.organization_id,
            org_perm=Perm.SESSION_READ_ORG,
        )


def test_reviewer_can_read_another_users_session_in_their_org() -> None:
    org_id = uuid.uuid4()
    principal = Principal.build(uuid.uuid4(), org_id, OrgRole.REVIEWER)
    authorize_owned(
        principal,
        owner_user_id=uuid.uuid4(),
        organization_id=org_id,
        org_perm=Perm.SESSION_READ_ORG,
    )


def test_reviewer_cannot_read_across_orgs() -> None:
    """Holding the capability is not enough -- the org has to match too."""
    principal = Principal.build(uuid.uuid4(), uuid.uuid4(), OrgRole.REVIEWER)
    with pytest.raises(PermissionError_):
        authorize_owned(
            principal,
            owner_user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),  # a different org
            org_perm=Perm.SESSION_READ_ORG,
        )


def test_unknown_role_is_denied_everything() -> None:
    """Fail closed: an unrecognised role resolves to no capabilities."""
    from app.authz.perms import permissions_for

    assert permissions_for("not-a-real-role") == frozenset()
