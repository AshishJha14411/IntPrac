"""The single policy layer. Every access decision goes through here.

⚠ Gate instances are created **once, at module level** (see ``gates.py``).
FastAPI's ``dependency_overrides`` keys on object identity, so an inline
``Depends(require(Perm.X))`` is un-overridable in tests -- the object you'd
need to override is created fresh on every import of the route module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.authz.perms import Perm, permissions_for
from app.core.errors import PermissionError_
from app.domain.enums import OrgRole


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking, and in which org.

    Built once per request by the auth dependency. Carrying the resolved
    permission set here (rather than re-deriving it at each call site) is what
    makes ``has_perm`` a pure function with no IO -- and therefore what keeps
    it out of the ``MissingGreenlet`` trap that comes from lazy-loading a role
    relationship inside an async request (Appendix D.4).
    """

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: OrgRole
    email_verified: bool = False
    permissions: frozenset[Perm] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        role: OrgRole | str,
        email_verified: bool = False,
    ) -> Principal:
        parsed = OrgRole(role)
        return cls(
            user_id=user_id,
            organization_id=organization_id,
            role=parsed,
            email_verified=email_verified,
            permissions=permissions_for(parsed),
        )


def has_perm(principal: Principal | None, perm: Perm) -> bool:
    return principal is not None and perm in principal.permissions


def require_perm(principal: Principal | None, perm: Perm) -> None:
    if not has_perm(principal, perm):
        raise PermissionError_(f"Requires capability '{perm.value}'.")


def authorize_owned(
    principal: Principal | None,
    *,
    owner_user_id: uuid.UUID,
    organization_id: uuid.UUID,
    org_perm: Perm | None = None,
) -> None:
    """Ownership check, with an optional org-level escape hatch.

    Two conditions, in this order:

    1. The caller owns the resource -> allowed.
    2. Otherwise, the caller must be in the resource's org **and** hold
       ``org_perm`` (e.g. a reviewer reading a session for their posting).

    Every data access is org-scoped *and* ownership-checked (NFR-SEC); this is
    the function that makes "and" true rather than aspirational.
    """
    if principal is None:
        raise PermissionError_("Authentication required.")
    if principal.user_id == owner_user_id:
        return
    if org_perm is not None and principal.organization_id == organization_id:
        require_perm(principal, org_perm)
        return
    # Deliberately the same message as a missing capability: we do not leak
    # "this resource exists but isn't yours" to a caller who can't see it.
    raise PermissionError_("You do not have access to this resource.")
