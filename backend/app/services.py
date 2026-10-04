from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AliasTaken, CodeGenerationFailed
from app.models import Link
from app.schemas import LinkCreate, LinkOut
from app.shortcode import generate_code

UNIQUE_VIOLATION = "23505"


def _is_unique_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION


def to_out(link: Link, settings: Settings) -> LinkOut:
    return LinkOut(
        code=link.code,
        short_url=f"{settings.base_url.rstrip('/')}/{link.code}",
        target_url=link.target_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
    )


async def create_link(
    session: AsyncSession,
    payload: LinkCreate,
    settings: Settings,
    owner_ip: str | None = None,
) -> Link:

    target = str(payload.target_url)

    if payload.custom_alias:
        link = Link(
            code=payload.custom_alias,
            target_url=target,
            is_custom=True,
            expires_at=payload.expires_at,
            owner_ip=owner_ip,
        )
        try:
            session.add(link)
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if _is_unique_violation(exc):
                raise AliasTaken(f"alias '{payload.custom_alias}' is already in use") from exc
            raise
        await session.refresh(link)
        return link

    for _ in range(settings.code_max_attempts):
        link = Link(
            code=generate_code(settings.code_length),
            target_url=target,
            is_custom=False,
            expires_at=payload.expires_at,
            owner_ip=owner_ip,
        )
        try:
            async with session.begin_nested():
                session.add(link)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                continue
            raise
        await session.commit()
        await session.refresh(link)
        return link

    raise CodeGenerationFailed(
        f"could not find a free code in {settings.code_max_attempts} attempts"
    )


async def get_link_by_code(session: AsyncSession, code: str) -> Link | None:
    result = await session.execute(select(Link).where(Link.code == code))
    return result.scalar_one_or_none()
