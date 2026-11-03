"""
Managed records: the screens that replace Django's admin.

The client is never to be sent to /admin/, which means every model a staff
member needs must have a screen here. Written once as a small registry rather
than as seven near-identical sets of list/create/edit/delete views, because
seven copies drift -- one grows a permission check, another forgets the search
box, and nobody notices until a Dispatcher can edit a rate card.

Anything with genuinely bespoke behaviour stays a hand-written view: the two
singleton settings screens, and the payment credentials, which are write-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Model, Q, QuerySet
from django.forms import BaseInlineFormSet, ModelForm


@dataclass(frozen=True)
class Column:
    """One column of a list screen."""

    header: str
    #: Attribute name, or a callable taking the instance.
    value: str | Callable[[Any], Any]
    #: Rendered as a muted second line under the main value.
    sub: str | Callable[[Any], Any] | None = None
    align_end: bool = False
    #: Renders as a green/grey pill rather than text.
    boolean: bool = False

    def resolve(self, instance) -> Any:
        return self._read(self.value, instance)

    def resolve_sub(self, instance) -> Any:
        return self._read(self.sub, instance) if self.sub else None

    @staticmethod
    def _read(source, instance):
        if callable(source):
            return source(instance)
        value = getattr(instance, source, "")
        return value() if callable(value) else value


@dataclass(frozen=True)
class Inline:
    """
    One inline formset shown beneath a managed record's own form.

    A record can carry more than one -- a vehicle has both its normal rate card
    and its city-to-city card -- so each is labelled and noted independently.
    The formset's own default prefix (its related-name accessor) keeps the two
    sets of POST fields apart, so no explicit prefix is needed here.
    """

    formset: type[BaseInlineFormSet]
    label: str = ""
    note: str = ""
    icon: str = "bi-rulers"


@dataclass(frozen=True)
class Managed:
    """
    One manageable model.

    `permission` is the Django permission required to *change* it. Viewing is
    derived from it (`view_` in place of `change_`), so a role that can read a
    rate card without editing it stays possible.
    """

    slug: str
    model: type[Model]
    form_class: type[ModelForm]
    label: str
    label_plural: str
    permission: str
    columns: list[Column]
    icon: str = "bi-collection"
    search_fields: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=lambda: ["pk"])
    #: Shown under the page title.
    lede: str = ""
    #: Guidance rendered above the form. Use it where a field is dangerous.
    form_note: str = ""
    can_delete: bool = True
    #: Inline formsets edited alongside the record, e.g. a vehicle's rate cards.
    inlines: list[Inline] = field(default_factory=list)
    #: Related names to select_related, to keep list screens off N+1.
    select_related: list[str] = field(default_factory=list)
    prefetch_related: list[str] = field(default_factory=list)

    @property
    def view_permission(self) -> str:
        return self.permission.replace("change_", "view_")

    def queryset(self) -> QuerySet:
        qs = self.model._default_manager.all()
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        return qs.order_by(*self.ordering)

    def search(self, qs: QuerySet, term: str) -> QuerySet:
        if not term or not self.search_fields:
            return qs
        query = Q()
        for name in self.search_fields:
            query |= Q(**{f"{name}__icontains": term})
        return qs.filter(query)


#: Populated by dashboard.managed at import time.
REGISTRY: dict[str, Managed] = {}


def register(entry: Managed) -> Managed:
    if entry.slug in REGISTRY:
        raise ValueError(f"Two managed records claim the slug {entry.slug!r}")
    REGISTRY[entry.slug] = entry
    return entry


def get(slug: str) -> Managed | None:
    return REGISTRY.get(slug)


def visible_to(user) -> list[Managed]:
    """The managed records this user may at least look at."""
    return [
        entry for entry in REGISTRY.values()
        if user.has_perm(entry.view_permission) or user.has_perm(entry.permission)
    ]
