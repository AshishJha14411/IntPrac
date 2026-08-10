"""Capabilities, and the role -> capability map.

Non-negotiable #4 (Appendix D.1): **authorization is asked, never inspected.**
Call sites ask ``has_perm(principal, Perm.X)``; nothing anywhere compares a
role-name string.

The map is built bottom-up so the hierarchy is expressed exactly once. Say
"an admin is a reviewer plus these extras" in one place and every downstream
check inherits it -- there is no second list to forget to update.
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.enums import OrgRole


class Perm(StrEnum):
    # --- own candidate surface ---
    RESUME_MANAGE = "resume:manage"
    JD_MANAGE = "jd:manage"
    SESSION_START = "session:start"
    SESSION_ANSWER = "session:answer"
    SESSION_READ_OWN = "session:read_own"
    REPORT_READ_OWN = "report:read_own"

    # --- reviewer surface (P3, modelled now so the map has one shape) ---
    SESSION_READ_ORG = "session:read_org"
    REVIEW_WRITE = "review:write"
    POSTING_MANAGE = "posting:manage"

    # --- administration ---
    ORG_MANAGE = "org:manage"
    MEMBER_MANAGE = "member:manage"
    BANK_MANAGE = "bank:manage"


#: Every authenticated user gets these for their own resources; ownership is a
#: separate check (`authorize_owned`), not a role.
_MEMBER: frozenset[Perm] = frozenset(
    {
        Perm.RESUME_MANAGE,
        Perm.JD_MANAGE,
        Perm.SESSION_START,
        Perm.SESSION_ANSWER,
        Perm.SESSION_READ_OWN,
        Perm.REPORT_READ_OWN,
    }
)

_REVIEWER: frozenset[Perm] = _MEMBER | {
    Perm.SESSION_READ_ORG,
    Perm.REVIEW_WRITE,
}

_ADMIN: frozenset[Perm] = _REVIEWER | {
    Perm.POSTING_MANAGE,
    Perm.MEMBER_MANAGE,
}

_OWNER: frozenset[Perm] = _ADMIN | {
    Perm.ORG_MANAGE,
    Perm.BANK_MANAGE,
}

ROLE_PERMISSIONS: dict[OrgRole, frozenset[Perm]] = {
    OrgRole.MEMBER: _MEMBER,
    OrgRole.REVIEWER: _REVIEWER,
    OrgRole.ADMIN: _ADMIN,
    OrgRole.OWNER: _OWNER,
}


def permissions_for(role: OrgRole | str) -> frozenset[Perm]:
    try:
        return ROLE_PERMISSIONS[OrgRole(role)]
    except ValueError:
        return frozenset()
